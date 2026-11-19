"""Entry point of the packaged desktop app (Vaelon.exe)."""
import sys

# Modules deliberately left out of the bundle. If a file with one of these names were dropped into the app folder, a
# `try: import x` somewhere would run it inside Vaelon - so they are refused outright (white-hat test 2026-11-18).
LEFT_OUT = ("faster_whisper", "ctranslate2", "torch", "tokenizers", "huggingface_hub", "hf_xet", "av", "sounddevice",
            "scipy", "pandas", "matplotlib", "IPython", "pytest", "flask", "werkzeug", "jinja2", "click", "pyttsx3",
            "comtypes", "yaml", "bcrypt", "setuptools", "pkg_resources", "bs4", "html5lib", "sitecustomize", "usercustomize")


class _LeftOut:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in LEFT_OUT:
            raise ImportError(f"{name} is not part of the installed Vaelon")
        return None


def _guard() -> None:
    if not getattr(sys, "frozen", False):
        return
    sys.meta_path.insert(0, _LeftOut())
    if sys.platform == "darwin":
        from vaelon import platform_mac

        if platform_mac.is_admin():  # never as root on a Mac either
            platform_mac.alert("Vaelon does not run as root - its tools would have full control of this Mac.")
            sys.exit(1)
        return
    try:
        import ctypes

        if ctypes.windll.shell32.IsUserAnAdmin():  # an assistant with file and command tools must not run as admin
            ctypes.windll.user32.MessageBoxW(
                None, "Vaelon does not run as administrator - its tools would have full control of this PC.\n"
                      "Start it normally (not with 'Run as administrator').", "Vaelon", 0x10)
            sys.exit(1)
        # one running copy at a time; the installer waits for it (AppMutex)
        ctypes.windll.kernel32.CreateMutexW(None, False, "VaelonRunning")
    except (AttributeError, OSError):
        pass


_guard()

from vaelon.cli import main  # noqa: E402

if __name__ == "__main__":
    main(["app"])
