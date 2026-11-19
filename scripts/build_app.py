"""Build the desktop app: dist/Vaelon/Vaelon.exe (Windows) - double-click to run, no terminal, no browser.

    python scripts/build_app.py            # needs Node (for the UI) and: pip install pyinstaller pywebview

Steps: build the web UI -> copy it into the package -> PyInstaller (one folder, windowed).
Ollama (the model server) stays a separate install; Vaelon talks to it on localhost.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "ui" / "web"
PKG = ROOT / "src" / "vaelon"
EXCLUDE = ["scipy", "pandas", "matplotlib", "tkinter", "faster_whisper", "ctranslate2", "av", "tokenizers",
           "huggingface_hub", "hf_xet", "IPython", "pytest", "sounddevice", "torch",
           # checked with the senior reviewer and the white-hat tester (2026-11-18): never imported by the desktop app
           "piper.train", "piper.http_server", "piper.__main__", "piper.hebrew", "piper.phonemize_hebrew",
           "flask", "werkzeug", "jinja2", "itsdangerous", "click", "blinker",
           "pyttsx3", "comtypes", "yaml", "bcrypt", "setuptools", "_distutils_hack", "pkg_resources",
           "bs4", "soupsieve", "html5lib", "lxml.objectify", "lxml.isoschematron", "lxml.html.diff",
           "lxml.html._difflib", "lxml.html.soupparser", "lxml.html.ElementSoup", "lxml.html.html5parser"]
# espeak dictionaries the app's voices (en_GB, en_US, bg) can reach: measured by sweeping every Unicode character
ESPEAK_KEEP = {"en", "bg", "bn", "el", "gd", "gu", "he", "hi", "hy", "ka", "kn", "ko", "ml", "pa", "si", "ta", "te"}


def run(cmd: list[str], cwd: Path) -> None:
    """Run one build step and stop the build when it fails. `npm` is npm.cmd on Windows: found with shutil.which."""
    exe = shutil.which(cmd[0]) or cmd[0]
    print("+", " ".join(cmd), flush=True)
    subprocess.run([exe, *cmd[1:]], cwd=str(cwd), check=True)


def _has(module: str) -> bool:
    """Whether a Python package is installed (optional parts are bundled only when present)."""
    import importlib.util

    return importlib.util.find_spec(module) is not None


def prune(internal: Path) -> None:
    """Data the module excludes cannot drop (--collect-all copies it as data). Nothing here is used by the app."""
    p = internal / "piper"
    shutil.rmtree(p / "hebrew", ignore_errors=True)  # Hebrew voices only (Vaelon's voices are English / Bulgarian)
    shutil.rmtree(p / "train", ignore_errors=True)
    (p / "tashkeel" / "model.onnx").unlink(missing_ok=True)  # Arabic voices only; the module itself stays (imported)
    data = p / "espeak-ng-data"
    for d in data.glob("*_dict"):
        if d.name[:-5] not in ESPEAK_KEEP:
            d.unlink()
    missing = [k for k in ESPEAK_KEEP if not (data / f"{k}_dict").is_file()]
    if missing or not (data / "phondata").is_file():
        sys.exit(f"espeak data incomplete: {missing}")
    (internal / "onnxruntime" / "capi" / "onnxruntime.dll").unlink(missing_ok=True)  # C API for native programs only
    # NOT removed: webview/lib/runtimes/win-arm64 and win-x86 - pythonnet checks that they exist and the window does not
    # open without them ("Cannot find win-arm64", found by the exe check 2026-11-18), although an x64 PC never loads them


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller missing:  pip install pyinstaller pywebview")
    if not (WEB / "node_modules").is_dir():
        run(["npm", "ci", "--no-audit", "--no-fund"], WEB)  # exactly the versions in package-lock.json
    run(["npm", "run", "build"], WEB)
    target = PKG / "webui"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(WEB / "out", target)
    sep = ";" if sys.platform == "win32" else ":"
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--noupx", "--name", "Vaelon",
         "--paths", str(ROOT / "src"),
         # the dotted V (scripts/make_icons.py); the app windows take their icon from the exe
         *(["--icon", str(PKG / "data" / "vaelon.ico")] if (PKG / "data" / "vaelon.ico").is_file() else []),
         "--add-data", f"{target}{sep}vaelon/webui",
         "--add-data", f"{PKG / 'data'}{sep}vaelon/data",
         "--collect-submodules", "vaelon",
         "--hidden-import", "webview",
         *(["--collect-all", "piper"] if _has("piper") else []),  # voice: espeak-ng data + models code
         # document makers keep templates/fonts next to their code
         *[x for m in ("docx", "pptx", "fpdf") if _has(m) for x in ("--collect-data", m)],
         *[x for m in ("docx", "pptx", "fpdf", "openpyxl", "pypdf", "websockets") if _has(m) for x in ("--hidden-import", m)],
         *(["--collect-submodules", "websockets"] if _has("websockets") else []),
         # not used by the desktop app (speech-to-text lives in `vaelon voice`): ~230 MB lighter
         *[x for m in EXCLUDE for x in ("--exclude-module", m)],
         str(PKG / "app_main.py")], ROOT)
    prune(ROOT / "dist" / "Vaelon" / "_internal")
    exe = ROOT / "dist" / "Vaelon" / ("Vaelon.exe" if sys.platform == "win32" else "Vaelon")
    print(f"\nDone: {exe}\nZip the folder dist/Vaelon to share it.")


if __name__ == "__main__":
    main()
