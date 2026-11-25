"""Open the winget update for a published Vaelon release (issue #26).

    python scripts/winget_update.py 0.20.0            # needs WINGET_TOKEN (see docs/PUBLISHING.md, section 8)
    python scripts/winget_update.py 0.20.0 --dry-run  # only writes the manifests to installer/winget/out/

What it does: reads the installer's SHA-256 from the published release (GitHub's own digest of the asset AND the line in
SHA256SUMS.txt - both must exist and agree), fills the three manifests in installer/winget/, puts them on a new branch of
the owner's fork of microsoft/winget-pkgs and opens the pull request "Update: Nokk_7.Vaelon to X.Y.Z".

Safety: only the Python standard library (nothing installed next to the token); the version must look like 1.2.3 (it
becomes part of paths and URLs); drafts and pre-releases are refused; the token comes only from the environment, is sent
only to api.github.com, never follows a redirect and is never printed; nothing is uploaded except three small text files.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "installer" / "winget"
REPO = "Nokk1251/vaelon"
FORK_OWNER = "Nokk1251"
UPSTREAM = "microsoft/winget-pkgs"
PACKAGE = "Nokk_7.Vaelon"
FOLDER = "manifests/n/Nokk_7/Vaelon"
AUTHOR = {"name": "Nokk_7", "email": "245811691+Nokk1251@users.noreply.github.com"}  # the public noreply address
VERSION_RX = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}")
SHA_RX = re.compile(r"[0-9a-fA-F]{64}")
API = "https://api.github.com/"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"


class Failed(Exception):
    pass


def clean_version(raw: str) -> str:
    v = raw.strip().removeprefix("v")
    if not VERSION_RX.fullmatch(v):
        raise Failed(f"not a release version: {raw[:40]!r}")
    return v


def render(version: str, sha256: str, date: str) -> dict[str, str]:
    """{file name: text} - the three manifests for this version."""
    version = clean_version(version)
    if not SHA_RX.fullmatch(sha256):
        raise Failed("not a SHA-256")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise Failed("not a date")
    out = {}
    for p in sorted(TEMPLATES.glob("*.yaml")):
        text = p.read_text("utf-8").replace("{{VERSION}}", version).replace("{{SHA256}}", sha256.upper())
        text = text.replace("{{DATE}}", date)
        if "{{" in text:
            raise Failed(f"{p.name}: a placeholder was left")
        out[p.name] = text
    if len(out) != 3:
        raise Failed("expected three manifest templates")
    return out


class Answer:
    def __init__(self, status: int, body: bytes):
        self.status_code, self.content = status, body

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content) if self.content else {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # a redirect is answered as its own status code - the token never travels on


class Http:
    """A tiny GitHub client on the standard library. The token goes only to api.github.com and never across a redirect."""

    def __init__(self, token: str | None):
        self.token = token
        self.api = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
        self.public = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # no token: follows redirects

    def request(self, method: str, url: str, json_body=None) -> Answer:
        if not url.startswith(API):
            raise Failed("refusing to send the token outside api.github.com")
        req = urllib.request.Request(url, method=method, data=None if json_body is None else json.dumps(json_body).encode())
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "vaelon-winget-update")
        if json_body is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        return self._send(self.api, req)

    def download(self, url: str) -> Answer:
        if not url.startswith(DOWNLOADS):
            raise Failed("unexpected download address")
        return self._send(self.public, urllib.request.Request(url, headers={"User-Agent": "vaelon-winget-update"}))

    @staticmethod
    def _send(opener, req) -> Answer:
        try:
            with opener.open(req, timeout=30) as r:
                return Answer(r.status, r.read(5_000_000))
        except urllib.error.HTTPError as e:
            return Answer(e.code, b"")
        except (urllib.error.URLError, OSError) as e:
            raise Failed(f"could not reach GitHub ({type(e).__name__})") from None


def _call(s, method: str, path: str, body=None, ok=(200, 201)):
    r = s.request(method, API + path, body)
    if r.status_code not in ok:
        raise Failed(f"{method} {path.split('?')[0]} answered HTTP {r.status_code}"
                     + (" - is the token missing the public_repo scope, or the fork gone?" if r.status_code in (401, 403)
                        else ""))
    return r.status_code, r.json()


def installer_sha(s, version: str) -> tuple[str, str]:
    """(SHA-256 of the published installer, its release date). GitHub's asset digest AND the line in SHA256SUMS.txt
    must both exist and agree."""
    _, rel = _call(s, "GET", f"repos/{REPO}/releases/tags/v{version}")
    if rel.get("draft") or rel.get("prerelease"):
        raise Failed("the release is a draft or a pre-release - only published releases go to winget")
    assets = {a["name"]: a for a in rel.get("assets", [])}
    name = f"Vaelon-Setup-{version}.exe"
    if name not in assets or "SHA256SUMS.txt" not in assets:
        raise Failed(f"{name} or SHA256SUMS.txt is missing from the release")
    digest = str(assets[name].get("digest") or "")
    if not (digest.startswith("sha256:") and SHA_RX.fullmatch(digest[7:])):
        raise Failed("GitHub gives no SHA-256 digest for the installer - stop")
    r = s.download(f"{DOWNLOADS}v{version}/SHA256SUMS.txt")
    if r.status_code != 200:
        raise Failed(f"SHA256SUMS.txt answered HTTP {r.status_code}")
    listed = [ln.split()[0] for ln in r.text.splitlines()
              if len(ln.split()) == 2 and ln.split()[1].lstrip("*") == name]
    if len(listed) != 1 or not SHA_RX.fullmatch(listed[0]):
        raise Failed("SHA256SUMS.txt has no single line for the installer")
    if digest[7:].lower() != listed[0].lower():
        raise Failed("GitHub's digest and SHA256SUMS.txt disagree - stop")
    return listed[0].upper(), str(rel.get("published_at") or dt.date.today().isoformat())[:10]


def plan(version: str, in_winget: list[str], open_prs: list[dict]) -> tuple[str, str]:
    """What to do, without the network: ("open", url) when our PR for this version is already open, ("stop", why), or
    ("send", title). `in_winget` = versions already in microsoft/winget-pkgs; `open_prs` = open PRs naming the package."""
    same = re.compile(rf"(?<![0-9.]){re.escape(version)}(?![0-9.])")  # 0.2.0 must not match 0.20.0
    for pr in open_prs:
        if same.search(pr.get("title", "")):
            if pr.get("user", {}).get("login") == FORK_OWNER:
                return "open", pr.get("html_url", "")
            return "stop", f"someone else already proposed {PACKAGE} {version}: {pr.get('html_url', '')}"
    if version in in_winget:
        return "stop", f"{PACKAGE} {version} is already in winget"
    if not in_winget:
        if open_prs:  # the first submission is still waiting: a second "New package" would only confuse the moderators
            return "stop", f"the first submission is not merged yet ({open_prs[0].get('html_url', '')}) - try again after it"
        return "send", f"New package: {PACKAGE} version {version}"
    return "send", f"Update: {PACKAGE} to {version}"


def submit(s, version: str, files: dict[str, str]) -> str:
    fork = f"{FORK_OWNER}/winget-pkgs"
    branch = f"{PACKAGE}-{version}"
    base = _call(s, "GET", f"repos/{UPSTREAM}")[1]["default_branch"]
    up_sha = _call(s, "GET", f"repos/{UPSTREAM}/git/ref/heads/{base}")[1]["object"]["sha"]
    code, listing = _call(s, "GET", f"repos/{UPSTREAM}/contents/{FOLDER}?ref={base}", ok=(200, 404))
    in_winget = [x["name"] for x in listing] if code == 200 and isinstance(listing, list) else []
    q = urllib.request.quote(f'repo:{UPSTREAM} is:pr is:open in:title "{PACKAGE}"')
    found = _call(s, "GET", f"search/issues?q={q}&per_page=30")[1].get("items", [])
    action, what = plan(version, in_winget, found)
    if action == "open":
        return what
    if action == "stop":
        raise Failed(what)
    code, _ = _call(s, "POST", f"repos/{fork}/git/refs", {"ref": f"refs/heads/{branch}", "sha": up_sha}, ok=(201, 422))
    if code == 422:  # 422 = the branch is left from an unfinished run (checked below) - start it again from upstream
        _call(s, "GET", f"repos/{fork}/git/ref/heads/{branch}")
        _call(s, "PATCH", f"repos/{fork}/git/refs/heads/{branch}", {"sha": up_sha, "force": True})
    tree = []
    for name, text in files.items():
        _, blob = _call(s, "POST", f"repos/{fork}/git/blobs",
                        {"content": base64.b64encode(text.encode("utf-8")).decode(), "encoding": "base64"})
        tree.append({"path": f"{FOLDER}/{version}/{name}", "mode": "100644", "type": "blob", "sha": blob["sha"]})
    base_tree = _call(s, "GET", f"repos/{fork}/git/commits/{up_sha}")[1]["tree"]["sha"]
    _, t = _call(s, "POST", f"repos/{fork}/git/trees", {"base_tree": base_tree, "tree": tree})
    _, c = _call(s, "POST", f"repos/{fork}/git/commits",
                 {"message": what, "tree": t["sha"], "parents": [up_sha], "author": AUTHOR, "committer": AUTHOR})
    _call(s, "PATCH", f"repos/{fork}/git/refs/heads/{branch}", {"sha": c["sha"], "force": True})
    body = (f"## 📖 Description\n{what}. The installer is `Vaelon-Setup-{version}.exe` from the project's GitHub release; "
            "its SHA-256 matches both GitHub's digest of the asset and `SHA256SUMS.txt`.\n\n"
            "## ✅ Checklist\n\n- [x] Signed the [Contributor License Agreement](https://cla.opensource.microsoft.com)\n\n"
            "## 📦 Manifest Checklist\n\n"
            "- [x] Checked that there aren't other open pull requests for the same manifest update/change\n"
            "- [x] This PR only modifies one (1) manifest\n"
            "- [x] Manifest conforms to the 1.28 schema\n")
    _, pr = _call(s, "POST", f"repos/{UPSTREAM}/pulls",
                  {"title": what, "head": f"{FORK_OWNER}:{branch}", "base": base, "body": body})
    return pr["html_url"]


def main(argv: list[str]) -> int:
    flags = [a for a in argv if a.startswith("--")]
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or any(f != "--dry-run" for f in flags):
        print("usage: python scripts/winget_update.py X.Y.Z [--dry-run]")
        return 2
    try:
        version = clean_version(args[0])
        token = os.environ.get("WINGET_TOKEN", "").strip()
        s = Http(token or os.environ.get("GITHUB_TOKEN", "").strip() or None)
        sha, date = installer_sha(s, version)
        files = render(version, sha, date)
        if flags:
            out = TEMPLATES / "out" / version
            out.mkdir(parents=True, exist_ok=True)
            for name, text in files.items():
                (out / name).write_text(text, "utf-8", newline="\n")
            print(f"manifests written to {out}")
            return 0
        if not token:
            note = "WINGET_TOKEN is not set: nothing was sent (see docs/PUBLISHING.md, section 8)."
            print(f"::warning::{note}" if os.environ.get("GITHUB_ACTIONS") else note)
            return 0
        print("winget pull request:", submit(s, version, files))
        return 0
    except Failed as e:
        print(f"winget update stopped: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
