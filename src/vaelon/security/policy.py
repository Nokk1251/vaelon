"""Risk levels, filesystem confinement and sensitive-path denylist."""
from __future__ import annotations

import enum
import re
import sys
from pathlib import Path


class Risk(enum.IntEnum):
    SAFE = 0  # read-only
    REVERSIBLE = 1  # changes state but an undo entry exists -> runs immediately
    DANGEROUS = 2  # irreversible / external effect (send, call, delete, shell, kill) -> human confirms


# .vaelon is Vaelon's own home (keys, config, plugins, memory): file tools may never touch it, so nothing
# (including injected instructions) can edit config.json to redirect an API key or plant a plugin.
SENSITIVE = (".ssh", ".gnupg", ".aws", ".azure", ".kube", ".vaelon", ".docker", ".config/gh", ".claude",
             "microsoft/protect", "microsoft/credentials", "microsoft/vault",
             # macOS: the keychains, browser and mail data, cookies
             "library/keychains", "library/cookies", "library/mail", "library/messages", "library/safari",
             "library/application support/google/chrome", "library/application support/firefox",
             "library/group containers/group.com.apple.notes")
SENSITIVE_NAMES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".env", "credentials", "cookies", "cookies.sqlite",
                   "login data", "local state", "web data", ".git-credentials", ".npmrc", ".pypirc", ".netrc", "_netrc",
                   "consolehost_history.txt", "key4.db", "logins.json", "credentials.json", ".credentials.json",
                   ".zsh_history", ".bash_history", ".python_history", ".lesshst")
# places where a written file runs by itself later (login, a new shell, a git command) and file types that are programs
AUTOSTART = ("/start menu/programs/startup/", "/windowspowershell/", "/powershell/", "/.git/hooks/", "/.vscode/tasks.json",
             # macOS / Unix: login items, launch agents, shell start-up files run code by themselves
             "/library/launchagents/", "/library/launchdaemons/", "/library/startupitems/", "/.zshrc/", "/.zprofile/",
             "/.zshenv/", "/.bashrc/", "/.bash_profile/", "/.profile/", "/.config/autostart/", "/crontab")
PROGRAM_EXT = {".sh", ".command", ".zsh", ".app", ".scpt", ".applescript", ".workflow", ".plist", ".dylib", ".py", ".pyw", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".lnk", ".url", ".exe", ".com",
               ".scr", ".msi", ".hta", ".reg", ".pif", ".cpl", ".dll", ".jar", ".inf", ".scf",
               # white-hat round 2: more programs, and files that make Windows / macOS / an app run something
               ".pth", ".ipy", ".fish", ".bash", ".ksh", ".csh", ".tcsh", ".vim", ".lua", ".rb", ".pl", ".php", ".cjs",
               ".mjs", ".desktop", ".service", ".timer", ".gradle", ".kts", ".pyd", ".so", ".psd1", ".ps1xml",
               ".xlsm", ".xlam", ".xla", ".xll", ".docm", ".dotm", ".pptm", ".ppam", ".appref-ms", ".application",
               ".library-ms", ".searchconnector-ms", ".settingcontent-ms", ".theme", ".themepack", ".msc", ".sct", ".wsc",
               ".chm", ".jnlp", ".terminal", ".fileloc", ".webloc", ".inetloc",
               ".xltm", ".potm", ".ppsm", ".sldm", ".xlsb", ".wll", ".rdp", ".website", ".appinstaller", ".appx", ".msix",
               ".msixbundle", ".diagcab", ".msp", ".mst", ".iso", ".img", ".vhd", ".vhdx", ".pkg", ".mpkg", ".prefpane",
               ".saver", ".kext", ".appimage"}
# A dot-file or anything inside a dot-folder is the settings of a shell, editor, git, a package manager or an app, and
# many of them run commands by themselves (.zlogin, .gitconfig, .git/config, .config/fish, .ipython, .vimrc ...): a
# list of names always misses some, so the RULE is "dot = asks". These few only hold lists of names and never run:
INERT_DOT = {".gitignore", ".editorconfig", ".dockerignore", ".prettierignore", ".eslintignore", ".npmignore"}
# per-user app settings areas (relative to the home folder); iCloud Drive inside Library holds the user's documents
APP_AREAS = ("appdata/", "library/")
# iCloud Drive and the cloud folders of Dropbox / OneDrive / Google Drive on a Mac, and the temp folder, hold documents
APP_AREAS_OK = ("library/mobile documents/", "library/cloudstorage/", "appdata/local/temp/")
RUN_NAMES = {"_vimrc", "_gvimrc", "desktop.ini"}


class PolicyError(Exception):
    pass


def _trailing(s: str) -> bool:
    """A file or folder name that ends with a dot or a space (Windows silently drops them)."""
    return any(x not in (".", "..") and x != x.rstrip(". ") for x in re.split(r"[\\/]", s) if x)


def odd_path(p: str) -> bool:
    """Windows tricks no real request needs: alternate data streams ("a.txt:hidden", "a.txt::$DATA"), device and
    raw-namespace paths (two backslashes then ? or .), CON / NUL / COM1 ..., network shares, control characters."""
    s = str(p).strip()
    if any(ord(c) < 32 for c in s) or ":" in s[2:]:
        return True
    if sys.platform == "win32" and _trailing(s):
        return True  # Windows drops trailing dots and spaces of a name: "run.bat." is saved as run.bat
    if s.startswith(("\\\\", "//")):
        return True
    stem = s.replace("/", "\\").rsplit("\\", 1)[-1].split(".")[0].upper()
    return stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or bool(re.fullmatch(r"(COM|LPT)[0-9]", stem))


def resolve_path(p: str, roots: list[str]) -> Path:
    if sys.platform == "win32" and _trailing(str(p).strip()):
        raise PolicyError("a file or folder name may not end with a dot or a space")
    if odd_path(p):
        raise PolicyError("that kind of path is not allowed (streams, devices, network shares)")
    path = Path(p).expanduser().resolve()
    rootps = [Path(r).expanduser().resolve() for r in roots]
    if not any(path == r or r in path.parents for r in rootps):
        raise PolicyError(f"path outside allowed roots: {path}")
    posix = path.as_posix()
    from .. import config

    home = config.HOME.expanduser().resolve()
    if path == home or home in path.parents:
        raise PolicyError("Vaelon's own data folder is protected")
    low = posix.lower() + "/"
    if any(f"/{s}/" in low for s in SENSITIVE + ("." + config.LEGACY_NAME,)) or path.name.lower() in SENSITIVE_NAMES:
        raise PolicyError(f"sensitive path is protected: {path.name}")
    return path


def _config_place(s: str) -> bool:
    """s = a lower-case path with '/' separators and a trailing '/'. A dot-file / dot-folder, a known run-by-itself
    name, or a per-user app settings area."""
    parts = [x for x in s.rstrip("/").split("/") if x]
    if parts and parts[-1] in INERT_DOT:
        parts = parts[:-1]
    if any(x.startswith(".") and x not in (".", "..") for x in parts):
        return True
    if parts and parts[-1].rstrip(". ") in RUN_NAMES:
        return True
    home = Path.home().resolve().as_posix().lower().rstrip("/") + "/"
    if s.startswith(home):
        rel = s[len(home):]
        return rel.startswith(APP_AREAS) and not rel.startswith(APP_AREAS_OK)
    return False


def runs_by_itself(p) -> bool:
    """True for a path where a written file becomes code that runs later (startup folder, shell / git / editor settings,
    git hook, app settings) or for a program / script / shortcut file. Writing there needs the user's approval every
    time."""
    raw = str(p).strip().strip('"')  # the file tools strip quotes too: '"x.bat"' must be seen as x.bat
    if not raw:
        return False
    if odd_path(raw):
        return True  # cannot tell safely: ask
    forms = [raw]
    try:
        # "STARTM~1", "..\.." and links are seen for what they are; a relative path is placed under the home folder
        # like the file tools do (never under the process's working folder)
        forms.append(str((Path.home() / Path(raw).expanduser()).resolve()))
    except (OSError, ValueError):
        pass
    for form in forms:
        s = form.replace("\\", "/").lower().rstrip("/") + "/"
        name = Path(s.rstrip("/")).name.rstrip(". ")  # Windows drops trailing dots and spaces: "x.bat." is x.bat
        if any(a in s for a in AUTOSTART) or "profile.ps1" in s or Path(name).suffix in PROGRAM_EXT or _config_place(s):
            return True
    return False


# commands that make something start by itself later (login items, launch agents, scheduled tasks, Run keys)
STARTS_ITSELF = re.compile(
    r"(?i)launchctl\s+(load|bootstrap|submit|enable)\b|defaults\s+write\b[^\n]*(loginhook|logouthook|loginwindow)"
    r"|login\s+item|\bcrontab\b|systemctl\s+--user\s+enable|schtasks\b[^\n]*/create|register-scheduledtask"
    r"|new-scheduledtask|currentversion\\+(run|runonce)\b|wmic\s+startup|\bsc(\.exe)?\s+create\b"
    r"|shell:startup|start menu\\+programs\\+startup|launchagents|winlogon|core\.(?:fsmonitor|hookspath)"
    r"|>>?\s*~?/?\.(?:zshrc|bashrc|profile|zprofile|zlogin|bash_profile)")
