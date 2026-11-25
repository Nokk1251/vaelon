"""Sign and verify release files with Vaelon's release key (issue #27) - in the minisign format, so anyone can check a
download with the standard `minisign` tool (`minisign -H -Vm FILE -P KEY`) as well as with this script.

The key lives OFFLINE on the owner's computer, encrypted with a password (scrypt + AES-256-GCM); it never goes to
GitHub. GitHub builds the draft release; the owner signs it from this computer, then publishes:

    python scripts/release_sign.py keygen  C:\\Users\\me\\vaelon-release.key   # once: asks for a password
    python scripts/release_sign.py keygen  NEW.key --pub-dir FOLDER          # a NEW key for a rotation
    python scripts/release_sign.py sign-draft 0.20.0 --key C:\\...\\vaelon-release.key
    python scripts/release_sign.py verify  Vaelon-Setup-0.20.0.exe          # anyone: checks FILE.minisig
    python scripts/release_sign.py check-all FOLDER                         # every file has a valid signature
    python scripts/release_sign.py sign FILE... --key KEYFILE               # sign single files

Format (minisign): public key = base64("Ed" | key id (8) | Ed25519 public key (32)); a signature file =
"untrusted comment" line, base64("ED" | key id | Ed25519 signature of BLAKE2b-512(file)), "trusted comment" line
("timestamp:N<TAB>file:NAME<TAB>hashed"), base64(Ed25519 signature of (file signature | trusted comment)).
"""
from __future__ import annotations

import base64
import binascii
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_KEY = ROOT / "release-key.pub"
REPO = "Nokk1251/vaelon"
MAX_SIG = 4096  # a signature file is ~300 bytes; anything big is not one
TRUSTED_RX = re.compile(r"timestamp:(\d+)\tfile:([^\t]*)\thashed")
KEY_MAGIC = b"VaelonRK1"
SCRYPT = {"n": 2 ** 17, "r": 8, "p": 1}  # ~128 MB and about a second per try: slow for guessing


class Failed(Exception):
    pass


def _ed():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    return ed25519, serialization


def _key_id_text(key_id: bytes) -> str:
    return key_id[::-1].hex().upper()  # minisign shows the id as a little-endian 64-bit number


def _pub_bytes(seed: bytes) -> bytes:
    ed, ser = _ed()
    return ed.Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)


def public_key_text(key_id: bytes, pub: bytes) -> str:
    return (f"untrusted comment: minisign public key {_key_id_text(key_id)} - Vaelon release key\n"
            f"{base64.b64encode(b'Ed' + key_id + pub).decode()}\n")


def read_public_key(text: str) -> tuple[bytes, bytes]:
    """(key id, public key) from a minisign public key file or bare key line."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("untrusted comment:")]
    try:
        raw = base64.b64decode(lines[0], validate=True)
    except (IndexError, binascii.Error):
        raise Failed("not a minisign public key") from None
    if len(raw) != 42 or raw[:2] != b"Ed":
        raise Failed("not a minisign Ed25519 public key")
    return raw[2:10], raw[10:]


# --- the secret key file: encrypted with the owner's password -------------------------------------------------------

def _derive(password: str, salt: bytes, params: bytes) -> bytes:
    log_n, r, p = params
    if not 10 <= log_n <= 20 or not 1 <= r <= 16 or not 1 <= p <= 4:
        raise Failed("unusual key-file parameters - refusing")
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** log_n, r=r, p=p, dklen=32,
                          maxmem=1024 * 1024 * 1024)


def _params() -> bytes:
    n = SCRYPT["n"]
    if n & (n - 1) or not 2 ** 10 <= n <= 2 ** 20:
        raise Failed("scrypt n must be a power of two")
    return bytes([n.bit_length() - 1, SCRYPT["r"], SCRYPT["p"]])


def seal_secret(key_id: bytes, seed: bytes, password: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    head = KEY_MAGIC + _params()
    salt, nonce = os.urandom(16), os.urandom(12)
    box = AESGCM(_derive(password, salt, head[-3:])).encrypt(nonce, key_id + seed, head)
    return ("untrusted comment: Vaelon release SECRET key - encrypted with a password; keep it private and backed up\n"
            + base64.b64encode(head + salt + nonce + box).decode() + "\n")


def open_secret(text: str, password: str) -> tuple[bytes, bytes]:
    """(key id, seed) from the encrypted key file; a wrong password or a changed file fails."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("untrusted comment:")]
    try:
        raw = base64.b64decode(lines[0], validate=True)
    except (IndexError, binascii.Error):
        raise Failed("not a Vaelon release key file") from None
    if not raw.startswith(KEY_MAGIC) or len(raw) != len(KEY_MAGIC) + 3 + 16 + 12 + 40 + 16:
        raise Failed("not a Vaelon release key file")
    head, salt, nonce, box = raw[:12], raw[12:28], raw[28:40], raw[40:]
    try:
        plain = AESGCM(_derive(password, salt, head[-3:])).decrypt(nonce, box, head)
    except InvalidTag:
        raise Failed("wrong password (or the key file was changed)") from None
    return plain[:8], plain[8:]


def _password(confirm: bool = False) -> str:
    """Always typed (never taken from the environment or a file)."""
    pw = getpass.getpass("Release key password: ")
    if confirm:
        if len(pw) < 12:
            raise Failed("use a password of at least 12 characters (a passphrase of a few words is best)")
        if getpass.getpass("Again: ") != pw:
            raise Failed("the two passwords differ")
    return pw


def load_key(path: Path) -> tuple[bytes, bytes]:
    """The secret key, which must belong to the published release-key.pub."""
    key_id, seed = open_secret(path.read_text("ascii"), _password())
    if (key_id, _pub_bytes(seed)) != read_public_key(PUBLIC_KEY.read_text("ascii")):
        raise Failed("this key does not match release-key.pub - stop")
    return key_id, seed


# --- signing and checking --------------------------------------------------------------------------------------------

def _blake(path: Path) -> bytes:
    h = hashlib.blake2b(digest_size=64)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.digest()


def sign_file(path: Path, key_id: bytes, seed: bytes, when: int | None = None) -> str:
    """The text of PATH.minisig."""
    ed, _ = _ed()
    sk = ed.Ed25519PrivateKey.from_private_bytes(seed)
    sig = sk.sign(_blake(path))
    name = path.name
    if any(ord(c) < 32 for c in name):
        raise Failed(f"{name!r}: control characters in a file name")
    trusted = f"timestamp:{int(time.time() if when is None else when)}\tfile:{name}\thashed"
    global_sig = sk.sign(sig + trusted.encode("utf-8"))
    return (f"untrusted comment: signature from Vaelon release key {_key_id_text(key_id)}\n"
            f"{base64.b64encode(b'ED' + key_id + sig).decode()}\n"
            f"trusted comment: {trusted}\n"
            f"{base64.b64encode(global_sig).decode()}\n")


def write_signature(path: Path, key_id: bytes, seed: bytes) -> None:
    text = sign_file(path, key_id, seed)
    tmp = Path(f"{path}.minisig.tmp")
    tmp.write_text(text, "utf-8", newline="\n")
    os.replace(tmp, f"{path}.minisig")  # never an empty or half-written .minisig


def verify_file(path: Path, sig_text: str, key_id: bytes, pub: bytes, expect_name: bool = True) -> str:
    """Raises Failed unless SIG_TEXT is a valid signature of PATH by this key; returns the trusted comment."""
    ed, _ = _ed()
    from cryptography.exceptions import InvalidSignature

    if len(sig_text.encode("utf-8")) > MAX_SIG:
        raise Failed(f"{path.name}: the signature file is too large to be one")
    lines = [ln.rstrip("\r") for ln in sig_text.split("\n")]
    if len(lines) < 4 or not lines[0].startswith("untrusted comment:") or not lines[2].startswith("trusted comment: "):
        raise Failed(f"{path.name}: not a minisign signature file")
    try:
        raw = base64.b64decode(lines[1].strip(), validate=True)
        global_sig = base64.b64decode(lines[3].strip(), validate=True)
    except binascii.Error:
        raise Failed(f"{path.name}: damaged signature file") from None
    if len(raw) != 74 or len(global_sig) != 64:
        raise Failed(f"{path.name}: damaged signature file")
    if raw[:2] != b"ED":  # only prehashed signatures (as `minisign -H`); Vaelon never makes the legacy kind
        raise Failed(f"{path.name}: not a prehashed (ED) signature")
    if raw[2:10] != key_id:
        raise Failed(f"{path.name}: signed with another key")
    sig = raw[10:]
    trusted = lines[2][len("trusted comment: "):]
    pk = ed.Ed25519PublicKey.from_public_bytes(pub)
    try:
        pk.verify(sig, _blake(path))
        pk.verify(global_sig, sig + trusted.encode("utf-8"))
    except InvalidSignature:
        raise Failed(f"{path.name}: the signature does not match - do not use this file") from None
    m = TRUSTED_RX.fullmatch(trusted)
    if expect_name and (not m or m.group(2) != path.name):
        signed = m.group(2) if m else "an unknown file"
        raise Failed(f"this signature is for {signed}, not {path.name} - a renamed (older?) file; if you renamed it "
                     "yourself, rename it back")
    return trusted


def check_all(folder: Path) -> int:
    """Every entry accounted for: only plain files, each with a valid signature, and no signature without its file."""
    key_id, pub = read_public_key(PUBLIC_KEY.read_text("ascii"))
    entries = sorted(folder.iterdir())
    for e in entries:
        if e.is_symlink() or not e.is_file():
            raise Failed(f"{e.name}: only plain files may be released")
    sigs = {e.name[:-len(".minisig")] for e in entries if e.name.endswith(".minisig")}
    files = [e for e in entries if not e.name.endswith(".minisig")]
    if not files:
        raise Failed("nothing to check")
    orphans = sigs - {f.name for f in files}
    if orphans:
        raise Failed(f"signature without its file: {sorted(orphans)[0]}.minisig")
    for p in files:
        sig = Path(f"{p}.minisig")
        if not sig.exists():
            raise Failed(f"{p.name} has no signature")
        if sig.stat().st_size > MAX_SIG:
            raise Failed(f"{sig.name} is too large to be a signature")
        verify_file(p, sig.read_text("utf-8"), key_id, pub)
    return len(files)


def check_sums(folder: Path) -> None:
    """Every downloaded file is listed in SHA256SUMS.txt with its exact hash (and nothing listed is missing)."""
    sums = folder / "SHA256SUMS.txt"
    if not sums.exists():
        raise Failed("SHA256SUMS.txt is missing from the draft")
    listed = {}
    for ln in sums.read_text("utf-8").split("\n"):
        if not ln.strip():
            continue
        parts = ln.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            raise Failed(f"SHA256SUMS.txt has a line that is not 'hash  name': {ln[:60]!r}")
        name = parts[1].lstrip("*")
        if name in listed:
            raise Failed(f"SHA256SUMS.txt lists {name} twice")
        listed[name] = parts[0].lower()
    files = {p.name for p in folder.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt"
             and not p.name.endswith(".minisig")}
    if files != set(listed):
        raise Failed(f"SHA256SUMS.txt does not list exactly the draft's files ({sorted(files ^ set(listed))[:3]})")
    for name, want in listed.items():
        h = hashlib.sha256()
        with (folder / name).open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            raise Failed(f"{name}: does not match SHA256SUMS.txt - stop")


def _gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise Failed(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def sign_draft(version: str, key_path: Path, gh=_gh) -> list[str]:
    """Download the DRAFT release, check SHA256SUMS, sign every file, check them all, upload the signatures."""
    if not re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", version):
        raise Failed(f"not a release version: {version[:40]!r}")
    tag = f"v{version}"
    listing = json.loads(gh("release", "list", "--repo", REPO, "--limit", "100", "--json", "tagName,isDraft"))
    same = [r for r in listing if r.get("tagName") == tag]
    if len(same) != 1:
        raise Failed(f"{len(same)} releases are named {tag} - delete the extra drafts first, then sign")
    info = json.loads(gh("release", "view", tag, "--repo", REPO, "--json", "isDraft,assets,url"))
    if not info.get("isDraft"):
        raise Failed(f"{tag} is not a draft - sign before publishing")
    print(f"Draft: {info.get('url', tag)}")
    key_id, seed = load_key(key_path)
    with tempfile.TemporaryDirectory(prefix="vaelon-sign-") as tmp:
        folder = Path(tmp)
        gh("release", "download", tag, "--repo", REPO, "--dir", str(folder))
        for old in folder.glob("*.minisig"):  # signing again replaces earlier signatures
            old.unlink()
        check_sums(folder)
        print("SHA256SUMS.txt of the draft - compare it with the 'Checksums' step in the log of the release run:")
        print((folder / "SHA256SUMS.txt").read_text("utf-8").rstrip())
        files = sorted(p for p in folder.iterdir() if p.is_file())
        for p in files:
            write_signature(p, key_id, seed)
        check_all(folder)
        sigs = [str(Path(f"{p}.minisig")) for p in files]
        gh("release", "upload", tag, "--repo", REPO, "--clobber", *sigs)
    after = json.loads(gh("release", "view", tag, "--repo", REPO, "--json", "assets"))
    names = {a["name"] for a in after.get("assets", [])}
    plain = {n for n in names if not n.endswith(".minisig")}
    missing = sorted(n for n in plain if f"{n}.minisig" not in names)
    extra = sorted(n for n in names if n.endswith(".minisig") and n[:-len(".minisig")] not in plain)
    if missing or extra:
        raise Failed(f"the draft is not consistent after the upload: unsigned {missing}, stray {extra} - remove the "
                     "stray files on the draft page and run sign-draft again")
    return [Path(s).name for s in sigs]


def keygen(out: Path, pub_dir: Path | None = None) -> str:
    """Make a release key: the SECRET goes, encrypted with a password, to OUT; the public key to release-key.pub (or,
    for a rotation, to PUB_DIR/release-key.pub, to be signed with the old key before it replaces the published one)."""
    ed, ser = _ed()
    raw = str(out)
    if raw.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")) or os.path.splitdrive(raw)[0].startswith(("\\\\", "//")) \
            or any(ord(c) < 32 for c in raw):
        raise Failed("use a normal local path for the key (no \\\\?\\, device or network paths)")
    real_out = os.path.normcase(os.path.realpath(out)).casefold()
    real_root = os.path.normcase(os.path.realpath(ROOT)).casefold()
    if real_out == real_root or real_out.startswith(real_root + os.sep):
        raise Failed("keep the secret key OUTSIDE the project folder (it must never be committed)")
    if out.exists():
        raise Failed(f"{out} already exists - never overwrite a key")
    pub_path = (pub_dir / PUBLIC_KEY.name) if pub_dir else PUBLIC_KEY
    if pub_path.exists():
        raise Failed(f"{pub_path} exists already - a new key needs a planned rotation (keygen --pub-dir, PUBLISHING 7b)")
    password = _password(confirm=True)
    seed = ed.Ed25519PrivateKey.generate().private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())
    key_id = os.urandom(8)
    sealed = seal_secret(key_id, seed, password)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(sealed)
    text = public_key_text(key_id, _pub_bytes(seed))
    pub_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pub_path, "x", encoding="ascii", newline="\n") as f:
        f.write(text)
    return text


def _opt(args: list[str], name: str) -> tuple[list[str], str | None]:
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            raise Failed(f"{name} needs a value")
        return args[:i] + args[i + 2:], args[i + 1]
    return args, None


def main(argv: list[str]) -> int:
    try:
        cmd, args = (argv[0], argv[1:]) if argv else ("", [])
        args, key = _opt(args, "--key")
        args, pub_dir = _opt(args, "--pub-dir")
        if cmd == "keygen" and len(args) == 1 and key is None:
            print(keygen(Path(args[0]), Path(pub_dir) if pub_dir else None), end="")
            print(f"Public key written to {Path(pub_dir) / PUBLIC_KEY.name if pub_dir else PUBLIC_KEY.name}. The "
                  f"encrypted SECRET key is in {args[0]}: back it up (see docs/PUBLISHING.md 7b).")
        elif cmd == "sign-draft" and len(args) == 1 and key:
            for name in sign_draft(args[0], Path(key)):
                print(f"signed and uploaded {name}")
            print("All files of the draft are signed. Check the draft page, then press Publish.")
        elif cmd == "sign" and args and key:
            key_id, seed = load_key(Path(key))
            for a in args:
                p = Path(a)
                if p.is_file() and not p.name.endswith(".minisig"):
                    write_signature(p, key_id, seed)
                    print(f"signed {p.name}")
                else:
                    print(f"skipped {a} (not a file, or a signature itself)")
        elif cmd == "verify" and args and key is None:
            key_id, pub = read_public_key(PUBLIC_KEY.read_text("ascii"))
            for a in args:
                p = Path(a)
                trusted = verify_file(p, Path(f"{p}.minisig").read_text("utf-8"), key_id, pub)
                print(f"OK  {p.name}  ({trusted})")
        elif cmd == "check-all" and len(args) == 1 and key is None:
            print(f"all {check_all(Path(args[0]))} files carry a valid signature")
        else:
            print("usage: release_sign.py keygen OUT [--pub-dir DIR] | sign-draft X.Y.Z --key KEYFILE | sign FILE... --key KEYFILE | "
                  "verify FILE... | check-all FOLDER")
            return 2
        return 0
    except (Failed, OSError, UnicodeError, ValueError) as e:
        print(f"release signing stopped: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
