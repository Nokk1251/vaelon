"""Guardian: Vaelon's built-in defences. All checks are LOCAL and DEFENSIVE.

- url_risk      : phishing / malicious-link heuristics, applied automatically before every web request
- content_risk  : malicious page patterns (obfuscated JS, miners, drive-by downloads), applied to fetched pages
- scan_path     : antivirus scan with the OS engine (Microsoft Defender on Windows, ClamAV elsewhere);
                  runs automatically on every download
- audit_machine : self-check of THIS computer (antivirus, firewall, open ports, autostart, suspicious
                  processes, Vaelon's own plugins)

It never attacks or probes other people's systems: scanning hosts you do not own is illegal without
permission, so "penetration tests" here are limited to your own machine.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

SUSPICIOUS_TLDS = {"zip", "mov", "xyz", "top", "tk", "ml", "ga", "cf", "gq", "work", "click", "country", "kim",
                   "loan", "men", "date", "racing", "download", "stream", "gdn", "bid", "review"}
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "rb.gy", "ow.ly", "shorturl.at"}
BRANDS = ["paypal", "microsoft", "apple", "google", "facebook", "instagram", "amazon", "netflix", "binance",
          "metamask", "dhl", "revolut", "dskbank", "postbank", "fibank", "unicredit", "steam", "discord"]
LURE_WORDS = ["login", "signin", "verify", "account", "secure", "update", "wallet", "confirm", "password", "bonus"]
RISKY_EXT = (".exe", ".scr", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jar", ".msi", ".hta", ".lnk", ".iso", ".apk")

CONTENT_PATTERNS = [
    (r"eval\s*\(\s*(atob|unescape|String\.fromCharCode)", "obfuscated JavaScript execution"),
    (r"document\.write\s*\(\s*unescape", "obfuscated document.write"),
    (r"(coinhive|cryptonight|webminer|coin-hive|minero\.cc)", "cryptocurrency miner"),
    (r"<iframe[^>]+(width|height)\s*=\s*['\"]?0", "hidden iframe"),
    (r"window\.location(\.href)?\s*=\s*['\"]data:", "data: URL redirect"),
    (r"(powershell(\.exe)?\s+-(e|enc|encodedcommand)\s)", "encoded PowerShell command"),
    (r"mshta(\.exe)?\s+(http|vbscript|javascript)", "mshta remote execution"),
    (r"(your (computer|pc) (is|has been) (infected|locked)|call (microsoft|windows) support)", "tech-support scam text"),
    (r"(seed phrase|recovery phrase|12[- ]word)", "asks for crypto seed phrase"),
]
_CONTENT_RX = [(re.compile(p, re.I), why) for p, why in CONTENT_PATTERNS]


def url_risk(url: str) -> tuple[int, list[str]]:
    """Score >= 3: block. 1-2: warn. 0: nothing found. Heuristics only - no data leaves the machine."""
    reasons: list[str] = []
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if not host:
        return 3, ["no host"]
    try:
        ipaddress.ip_address(host)
        reasons.append("raw IP address instead of a domain")
    except ValueError:
        pass
    if "xn--" in host:
        reasons.append("punycode domain (possible look-alike/homograph)")
    if u.username or "@" in u.netloc:
        reasons.append("credentials/@ in the link (disguised destination)")
    tld = host.rsplit(".", 1)[-1]
    if tld in SUSPICIOUS_TLDS:
        reasons.append(f"high-abuse domain ending .{tld}")
    if host in SHORTENERS:
        reasons.append("URL shortener hides the destination")
    if host.count(".") >= 4 or len(host) > 60:
        reasons.append("unusually long/deep domain")
    parts = host.split(".")
    registered = ".".join(parts[-2:])
    for b in BRANDS:
        if b in host and not registered.startswith(b):
            reasons.append(f"mentions '{b}' but the real domain is {registered}")
            break
    if any(w in (u.path + u.query).lower() for w in LURE_WORDS) and reasons:
        reasons.append("login/verify lure on a suspicious domain")
    if u.path.lower().endswith(RISKY_EXT):
        reasons.append("links directly to an executable/script file")
    if u.scheme == "http":
        reasons.append("not encrypted (http)")
    score = len(reasons) + (1 if any("mentions" in r for r in reasons) else 0)
    return score, reasons


def content_risk(text: str) -> list[str]:
    return sorted({why for rx, why in _CONTENT_RX if rx.search(text or "")})


def _defender() -> str | None:
    if sys.platform != "win32":
        return None
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),):
        p = Path(base) / "Windows Defender" / "MpCmdRun.exe"
        if p.exists():
            return str(p)
    return None


def mark_from_internet(path: str | Path) -> None:
    """Mark a file as coming from the internet, the way a browser does: Windows "Mark of the Web" (Office opens it in
    Protected View, macros of internet files are blocked, SmartScreen checks programs) and the macOS quarantine flag
    (Gatekeeper checks it before anything runs). Best effort - never fails the download or the upload."""
    import time

    try:
        if sys.platform == "win32":
            with open(str(path) + ":Zone.Identifier", "w", encoding="utf-8") as z:
                z.write("[ZoneTransfer]\r\nZoneId=3\r\n")
        elif sys.platform == "darwin":
            subprocess.run(["xattr", "-w", "com.apple.quarantine", f"0081;{int(time.time()):x};Vaelon;", str(path)],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def scan_path(path: str | Path, timeout: int = 600) -> tuple[bool | None, str]:
    """(True clean | False threat found | None no scanner, details)."""
    path = str(path)
    exe = _defender()
    if exe:
        r = subprocess.run([exe, "-Scan", "-ScanType", "3", "-File", path, "-DisableRemediation"],
                           capture_output=True, text=True, timeout=timeout, errors="replace")
        out = (r.stdout + r.stderr).strip()
        if r.returncode == 0:
            return True, "Microsoft Defender: no threats found"
        if r.returncode == 2:
            return False, "Microsoft Defender: THREAT FOUND\n" + out[-800:]
        return None, f"Microsoft Defender could not scan (code {r.returncode}): {out[-300:]}"
    clam = shutil.which("clamscan")
    if clam:
        r = subprocess.run([clam, "--no-summary", "-r", path], capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return True, "ClamAV: no threats found"
        if r.returncode == 1:
            return False, "ClamAV: THREAT FOUND\n" + r.stdout[-800:]
        return None, "ClamAV error: " + r.stderr[-300:]
    return None, "no antivirus engine available (install ClamAV on macOS/Linux)"


def _ps(cmd: str, timeout: int = 60) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.stdout.strip()
    except Exception as e:
        return f"(unavailable: {e})"


def audit_machine() -> list[tuple[str, str]]:
    """Returns [(severity, finding)], severity in HIGH/MEDIUM/LOW/OK."""
    findings: list[tuple[str, str]] = []
    if sys.platform == "win32":
        av = _ps("$s=Get-MpComputerStatus; \"$($s.AntivirusEnabled)|$($s.RealTimeProtectionEnabled)|"
                 "$($s.AntivirusSignatureAge)\"")
        if "|" in av:
            enabled, realtime, age = (av.split("|") + ["", "", ""])[:3]
            findings.append(("OK" if enabled == "True" else "HIGH", f"Antivirus enabled: {enabled}"))
            findings.append(("OK" if realtime == "True" else "HIGH", f"Real-time protection: {realtime}"))
            if age.isdigit():
                findings.append(("OK" if int(age) <= 3 else "MEDIUM", f"Virus definitions age: {age} day(s)"))
        else:
            findings.append(("MEDIUM", "Could not read Microsoft Defender status " + av[:120]))
        fw = _ps("Get-NetFirewallProfile | ForEach-Object { \"$($_.Name)=$($_.Enabled)\" }")
        for line in fw.splitlines():
            if "=" in line:
                name, on = line.split("=", 1)
                findings.append(("OK" if on.strip() == "True" else "HIGH", f"Firewall {name.strip()}: {on.strip()}"))
        run_keys = _ps("Get-ItemProperty HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run, "
                       "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run -ErrorAction SilentlyContinue | "
                       "ForEach-Object { $_.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' } | "
                       "ForEach-Object { \"$($_.Name) => $($_.Value)\" } }")
        for line in run_keys.splitlines()[:40]:
            low = line.lower()
            sev = "MEDIUM" if any(s in low for s in ("\\temp\\", "\\appdata\\local\\temp", "powershell -e",
                                                      "mshta", "wscript", ".vbs", "\\users\\public\\")) else "LOW"
            findings.append((sev, f"Autostart: {line.strip()[:160]}"))
    try:
        import psutil

        listening = {}
        for c in psutil.net_connections(kind="inet"):
            if c.status == psutil.CONN_LISTEN and c.laddr:
                exposed = c.laddr.ip not in ("127.0.0.1", "::1")
                try:
                    name = psutil.Process(c.pid).name() if c.pid else "?"
                except Exception:
                    name = "?"
                listening[(c.laddr.port, name)] = listening.get((c.laddr.port, name), False) or exposed
        for (port, name), exposed in sorted(listening.items())[:40]:
            system_proc = name.lower() in ("system", "svchost.exe", "services.exe", "lsass.exe", "wininit.exe",
                                           "spoolsv.exe", "?")
            findings.append(("MEDIUM" if exposed and not system_proc else "LOW",
                             f"Listening port {port} ({name}){' - reachable from the network' if exposed else ''}"))
        for p in psutil.process_iter(["name", "exe"]):
            exe = (p.info.get("exe") or "").lower()
            if exe and any(s in exe for s in ("\\appdata\\local\\temp\\", "\\windows\\temp\\", "/tmp/")):
                findings.append(("HIGH", f"Process running from a temp folder: {p.info['name']} ({exe})"))
    except ImportError:
        findings.append(("LOW", 'Install psutil for port/process checks: pip install "vaelon[system]"'))
    from . import config
    from .tools.evolve import validate_plugin

    plug = config.HOME / "plugins"
    for f in sorted(plug.glob("*.py")) if plug.is_dir() else []:
        problems = validate_plugin(f.read_text("utf-8", errors="replace"))
        if problems:
            findings.append(("MEDIUM", f"Vaelon plugin {f.name}: {'; '.join(problems)[:160]}"))
    return findings
