"""Code research: Vaelon studies open-source projects on GitHub to learn better techniques.

It reads READMEs and (optionally) one source file of the top repositories for a topic, distils the
techniques into memory with repository, stars and LICENSE recorded, so it can later propose improvements
to itself (through `self_modify`, which still needs your approval and passing tests).
Code is learned as IDEAS; copying code is only acceptable when the licence allows it (MIT/Apache/BSD...)
and the source is credited. Set GITHUB_TOKEN for higher API limits (optional).
"""
from __future__ import annotations

import requests

from .. import config
from ..security import audit, ssrf
from .registry import tool

API = "https://api.github.com"
PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "0BSD", "MPL-2.0"}


def _gh(path: str, raw: bool = False, params: dict | None = None):
    url = f"{API}{path}"
    ssrf.check_url(url)
    h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
         "User-Agent": "Vaelon-agent"}
    tok = config.env("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    r = requests.get(url, headers=h, params=params, timeout=20)
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise RuntimeError("GitHub rate limit reached - wait a minute or set GITHUB_TOKEN")
    r.raise_for_status()
    return r.text if raw else r.json()


def top_repos(topic: str, language: str = "", limit: int = 3) -> list[dict]:
    q = topic + (f" language:{language}" if language else "")
    items = _gh("/search/repositories", params={"q": q, "sort": "stars", "order": "desc", "per_page": limit})["items"]
    return [{"name": i["full_name"], "stars": i["stargazers_count"], "url": i["html_url"],
             "license": (i.get("license") or {}).get("spdx_id") or "none", "desc": i.get("description") or ""}
            for i in items[:limit]]


@tool("research_code", "Study the best open-source projects on GitHub for a topic and remember their techniques "
      "(with licence), to improve your own code and answers", {"topic": "what to research", "?language": "e.g. python"},
      untrusted=True, group="learning")
def research_code(ctx, topic, language=""):
    from ..learning import distill

    agent = ctx.extra.get("agent")
    if agent is None:
        return "ERROR: research needs the agent's language model"
    repos = top_repos(topic, language)
    if not repos:
        return "no repositories found"
    report = []
    for repo in repos:
        try:
            readme = _gh(f"/repos/{repo['name']}/readme", raw=True)
        except Exception as e:
            report.append(f"- {repo['name']}: could not read README ({e})")
            continue
        facts = distill(agent.llm, f"techniques and design ideas for {topic}", readme, n=5)
        reuse = "code reusable with credit" if repo["license"] in PERMISSIVE else "ideas only (licence does not allow copying)"
        for f in facts:
            ctx.memory.add(f"{f} [from {repo['url']}, {repo['stars']} stars, licence {repo['license']}: {reuse}]",
                           kind="code-insight")
        report.append(f"- {repo['name']} ({repo['stars']}★, {repo['license']}, {reuse}): "
                      + ("; ".join(facts) if facts else "nothing useful extracted"))
    audit.log("research_code", topic=topic, repos=[r["name"] for r in repos])
    return f"Studied {len(repos)} projects on '{topic}':\n" + "\n".join(report)

