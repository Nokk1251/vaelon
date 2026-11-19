"""Security tools exposed to the agent (all defensive, all local)."""
from __future__ import annotations

from .. import guardian
from ..security.policy import resolve_path
from .registry import tool


@tool("check_url", "Check whether a link looks like phishing or malware (local heuristics, nothing is opened)",
      {"url": "the link"}, group="security")
def check_url(ctx, url):
    score, reasons = guardian.url_risk(url)
    verdict = "DANGEROUS - do not open" if score >= 3 else "SUSPICIOUS - be careful" if score else "no red flags found"
    return f"{verdict} (score {score})" + "".join(f"\n- {r}" for r in reasons)


@tool("scan_file", "Scan a file or folder for viruses with the system antivirus (Microsoft Defender / ClamAV)",
      {"path": "file or folder"}, group="security")
def scan_file(ctx, path):
    p = resolve_path(path, ctx.cfg.allowed_roots)
    clean, detail = guardian.scan_path(p)
    head = {True: "CLEAN", False: "THREAT FOUND", None: "NOT SCANNED"}[clean]
    return f"{head}: {p}\n{detail}"


@tool("security_audit", "Security self-check of THIS computer: antivirus, firewall, open ports, autostart, "
      "suspicious processes, Vaelon plugins", group="security")
def security_audit(ctx):
    findings = guardian.audit_machine()
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "OK": 3}
    findings.sort(key=lambda f: order.get(f[0], 9))
    counts = {s: sum(1 for f in findings if f[0] == s) for s in order}
    head = f"HIGH {counts['HIGH']} | MEDIUM {counts['MEDIUM']} | LOW {counts['LOW']} | OK {counts['OK']}"
    return head + "\n" + "\n".join(f"[{s}] {t}" for s, t in findings)
