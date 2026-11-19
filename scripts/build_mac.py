"""Build the Mac app and its disk image: dist/Vaelon.app and dist/Vaelon-<version>.dmg.

    python3 scripts/build_mac.py        # on a Mac (macOS 14+, Apple silicon), with Node, Python 3.13 and the app extras installed:
                                        # pip install -e ".[system,search,docs,vision,app,mac]" "piper-tts>=1.2" numpy pyinstaller

Apple builds Mac apps only on a Mac, so this runs there (or on GitHub's free macOS machines, see
.github/workflows/release.yml). No paid Apple account is used: the app is signed AD-HOC (free, required on Apple
silicon) and not notarised, so the first time a user opens it macOS asks once - System Settings > Privacy & Security >
"Open Anyway". Nothing else about the app changes.
"""
from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_app import EXCLUDE, PKG, WEB, _has, prune, run  # noqa: E402  - the same choices as the Windows build

sys.path.insert(0, str(ROOT / "src"))
from vaelon import __version__  # noqa: E402

BUNDLE_ID = "io.github.nokk1251.vaelon"
# what the Mac shows when Vaelon first asks for the microphone / the screen (the app asks; the user decides)
USAGE = {
    "NSMicrophoneUsageDescription": "Vaelon listens when you talk to it (push-to-talk, hands-free or Live voice).",
    "NSScreenCaptureUsageDescription": "Vaelon looks at your screen only while you switch the eye on.",
    "NSAppleEventsUsageDescription": "Vaelon shows notifications and opens the files it made for you.",
}


def icns() -> Path:
    """The app icon as .icns (from the same artwork as the Windows icon)."""
    from PIL import Image

    out = ROOT / "build" / "vaelon.icns"
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.open(PKG / "data" / "vaelon.ico").save(out, sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256)])
    return out


def drop_broken_links(root: Path) -> list[str]:
    """PyInstaller links the data files of Contents/Frameworks to Contents/Resources (and back). prune() deletes files
    the app never uses, which leaves links that point nowhere - and `codesign --verify --strict` refuses a bundle with
    a broken link ("No such file or directory"). Remove them; return what was removed."""
    gone = []
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):  # deepest first
        if p.is_symlink() and not p.exists():
            p.unlink()
            gone.append(str(p.relative_to(root)))
    return gone


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("build_mac.py runs on a Mac (Apple builds Mac apps only on macOS). On Windows use build_app.py.")
    if not (WEB / "node_modules").is_dir():
        run(["npm", "ci", "--no-audit", "--no-fund"], WEB)
    run(["npm", "run", "build"], WEB)
    target = PKG / "webui"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(WEB / "out", target)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--noupx", "--name", "Vaelon",
         "--osx-bundle-identifier", BUNDLE_ID, "--icon", str(icns()), "--paths", str(ROOT / "src"),
         "--add-data", f"{target}:vaelon/webui", "--add-data", f"{PKG / 'data'}:vaelon/data",
         "--collect-submodules", "vaelon", "--hidden-import", "webview", "--hidden-import", "keyring.backends.macOS",
         *(["--collect-all", "piper"] if _has("piper") else []),
         *[x for m in ("docx", "pptx", "fpdf") if _has(m) for x in ("--collect-data", m)],
         *[x for m in ("docx", "pptx", "fpdf", "openpyxl", "pypdf", "websockets") if _has(m) for x in ("--hidden-import", m)],
         *(["--collect-submodules", "websockets"] if _has("websockets") else []),
         *[x for m in EXCLUDE for x in ("--exclude-module", m)],
         str(PKG / "app_main.py")], ROOT)
    app = ROOT / "dist" / "Vaelon.app"
    for internal in (app / "Contents" / "Resources", app / "Contents" / "Frameworks"):  # PyInstaller 6 splits data / code
        if (internal / "piper" / "espeak-ng-data").is_dir():
            prune(internal)
    gone = drop_broken_links(app)
    print(f"removed {len(gone)} links to left-out files" + (": " + ", ".join(gone[:10]) if gone else ""))
    info = app / "Contents" / "Info.plist"
    data = plistlib.loads(info.read_bytes())
    data.update(USAGE)
    data.update({"CFBundleShortVersionString": __version__, "CFBundleVersion": __version__, "LSMinimumSystemVersion": "14.0",
                 "NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.productivity"})
    info.write_bytes(plistlib.dumps(data))
    # ad-hoc signature (free): required for Apple-silicon binaries; re-done after Info.plist changed
    run(["codesign", "--force", "--deep", "--sign", "-", str(app)], ROOT)  # no hardened runtime: that needs a paid ID
    check = subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=4", str(app)], capture_output=True,
                           text=True)
    print(check.stdout + check.stderr)  # names the exact file when the signature check fails
    if check.returncode:
        sys.exit("codesign --verify failed - see the lines above")
    # the disk image: the app next to a link to Applications (drag to install)
    stage = ROOT / "build" / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run(["ditto", str(app), str(stage / "Vaelon.app")], ROOT)
    (stage / "Applications").symlink_to("/Applications")
    dmg = ROOT / "dist" / f"Vaelon-{__version__}.dmg"
    dmg.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", "Vaelon", "-srcfolder", str(stage), "-ov", "-format", "UDZO", str(dmg)], ROOT)
    print(f"\nDone: {dmg}")
    subprocess.run(["shasum", "-a", "256", str(dmg)])


if __name__ == "__main__":
    main()
