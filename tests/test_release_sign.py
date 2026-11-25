"""Release signing (issue #27): an offline, password-protected key signs files in the minisign format; every kind of
tampering is caught; the draft flow downloads, checks SHA256SUMS, signs and uploads. Temp folders only - nothing here
touches the project's release-key.pub, a real key, GitHub or the network."""
import base64
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import release_sign as R  # noqa: E402

PASSWORD = "correct horse battery staple"


def quiet(fn, *a):
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
        code = fn(*a)
    return code, out.getvalue() + err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "keys").mkdir()
        self.real = (R.PUBLIC_KEY, R.SCRYPT, R.getpass.getpass)
        R.PUBLIC_KEY = self.dir / "keys" / "release-key.pub"
        R.SCRYPT = {"n": 2 ** 12, "r": 8, "p": 1}  # fast for the tests; the real file uses 2**17
        self.typed = PASSWORD
        R.getpass.getpass = lambda prompt="": self.typed  # what the owner would type
        self.keyfile = self.dir / "secret" / "vaelon-release.key"
        code, self.printed = quiet(R.main, ["keygen", str(self.keyfile)])
        self.assertEqual(code, 0, self.printed)
        self.key_id, self.pub = R.read_public_key(R.PUBLIC_KEY.read_text("ascii"))
        self.files = self.dir / "release"
        self.files.mkdir()
        self.file = self.files / "Vaelon-Setup-9.9.9.exe"
        self.file.write_bytes(os.urandom(300_000))

    def tearDown(self):
        R.PUBLIC_KEY, R.SCRYPT, R.getpass.getpass = self.real

    def sign(self, path=None):
        code, out = quiet(R.main, ["sign", str(path or self.file), "--key", str(self.keyfile)])
        self.assertEqual(code, 0, out)
        return Path(f"{path or self.file}.minisig")


class Key(Base):
    def test_the_secret_is_encrypted_and_never_printed(self):
        text = self.keyfile.read_text("ascii")
        key_id, seed = R.open_secret(text, PASSWORD)
        self.assertEqual(key_id, self.key_id)
        for shown in (text, self.printed):
            self.assertNotIn(base64.b64encode(seed).decode()[:16], shown)
            self.assertNotIn(seed.hex()[:16], shown)
        with self.assertRaises(R.Failed):
            R.open_secret(text, "wrong password")
        lines = text.splitlines()
        raw = bytearray(base64.b64decode(lines[1]))
        raw[-1] ^= 1
        with self.assertRaises(R.Failed):  # a changed key file is refused, not silently used
            R.open_secret(lines[0] + "\n" + base64.b64encode(bytes(raw)).decode(), PASSWORD)

    def test_the_password_is_never_taken_from_the_environment(self):
        self.assertFalse(hasattr(R, "PASSWORD_ENV"))
        self.assertNotIn("os.environ", Path(R.__file__).read_text("utf-8"))

    def test_the_scrypt_settings_travel_with_the_key_file(self):
        R.SCRYPT = {"n": 2 ** 13, "r": 8, "p": 1}  # a later default must still open an older key file
        R.load_key(self.keyfile)

    def test_a_wrong_password_signs_nothing(self):
        self.typed = "nope"
        code, _ = quiet(R.main, ["sign", str(self.file), "--key", str(self.keyfile)])
        self.assertEqual(code, 1)
        self.assertFalse(Path(f"{self.file}.minisig").exists())

    def test_a_short_or_mistyped_password_is_refused_at_keygen(self):
        R.PUBLIC_KEY.unlink()
        for answers in (["short", "short"], ["a long passphrase here", "a long passphrase HERE"]):
            it = iter(answers)
            R.getpass.getpass = lambda prompt="": next(it)
            code, out = quiet(R.main, ["keygen", str(self.dir / "other.key")])
            self.assertEqual(code, 1, out)
            self.assertFalse((self.dir / "other.key").exists() or R.PUBLIC_KEY.exists())

    def test_a_rotation_signs_the_new_public_key_with_the_old_one(self):
        new_dir = self.dir / "next"
        code, out = quiet(R.main, ["keygen", str(self.dir / "new.key"), "--pub-dir", str(new_dir)])
        self.assertEqual(code, 0, out)
        new_pub = new_dir / "release-key.pub"
        self.assertNotEqual(new_pub.read_text("ascii"), R.PUBLIC_KEY.read_text("ascii"))
        self.sign(new_pub)  # with the OLD key: it still matches the published release-key.pub
        R.verify_file(new_pub, Path(f"{new_pub}.minisig").read_text("utf-8"), self.key_id, self.pub)

    def test_a_key_is_never_made_inside_the_project_over_another_or_on_odd_paths(self):
        R.PUBLIC_KEY.unlink()
        bad_paths = [ROOT / "never-here.key", str(ROOT / "NEVER-HERE-2.key"), str(self.dir / "a\x0bb.key")]
        if os.name == "nt":  # Windows path forms; on other systems these are ordinary file names
            bad_paths += ["\\\\?\\" + str(ROOT / "never2.key"), "\\\\server\\share\\x.key"]
        for bad in bad_paths:
            code, _ = quiet(R.main, ["keygen", str(bad)])
            self.assertEqual(code, 1, bad)
        self.assertFalse(any((ROOT / n).exists() for n in ("never-here.key", "NEVER-HERE-2.key", "never2.key")))
        code, _ = quiet(R.main, ["keygen", str(self.keyfile)])  # exists already
        self.assertEqual(code, 1)

    def test_a_second_keygen_never_replaces_the_public_key(self):
        before = R.PUBLIC_KEY.read_text("ascii")
        code, _ = quiet(R.main, ["keygen", str(self.dir / "second.key")])
        self.assertEqual(code, 1)
        self.assertEqual(R.PUBLIC_KEY.read_text("ascii"), before)
        self.assertFalse((self.dir / "second.key").exists())

    def test_a_key_that_does_not_match_the_published_one_signs_nothing(self):
        other = self.dir / "other.key"
        other.write_text(R.seal_secret(os.urandom(8), os.urandom(32), PASSWORD), "ascii")
        code, out = quiet(R.main, ["sign", str(self.file), "--key", str(other)])
        self.assertEqual(code, 1)
        self.assertIn("does not match", out)


class Signature(Base):
    def test_the_formats_are_minisign(self):
        pub_line = R.PUBLIC_KEY.read_text("ascii").splitlines()[1]
        self.assertTrue(pub_line.startswith("RW") and len(base64.b64decode(pub_line)) == 42)  # "Ed" + id + key
        lines = self.sign().read_text("utf-8").splitlines()
        self.assertTrue(lines[0].startswith("untrusted comment:") and lines[2].startswith("trusted comment: timestamp:"))
        self.assertTrue(lines[1].startswith("RU") and len(base64.b64decode(lines[1])) == 74)  # "ED" = prehashed
        self.assertIn("\tfile:Vaelon-Setup-9.9.9.exe\thashed", lines[2])

    def test_a_good_signature_verifies_and_check_all_accounts_for_everything(self):
        self.sign()
        code, out = quiet(R.main, ["verify", str(self.file)])
        self.assertEqual(code, 0, out)
        self.assertEqual(R.check_all(self.files), 1)
        (self.files / "SHA256SUMS.txt").write_text("unsigned", "ascii")
        with self.assertRaises(R.Failed):  # a file without a signature
            R.check_all(self.files)
        (self.files / "SHA256SUMS.txt").unlink()
        (self.files / "Evil.exe.minisig").write_bytes(b"MZ" + os.urandom(100))
        with self.assertRaises(R.Failed):  # a signature without its file (could carry anything)
            R.check_all(self.files)
        (self.files / "Evil.exe.minisig").unlink()
        (self.files / "folder").mkdir()
        with self.assertRaises(R.Failed):  # only plain files
            R.check_all(self.files)

    def test_every_tampering_is_caught(self):
        sig = self.sign().read_text("utf-8")
        key = (self.key_id, self.pub)
        changed = bytearray(self.file.read_bytes())
        changed[1000] ^= 1
        other = self.files / "Vaelon-Setup-9.9.9b.exe"
        other.write_bytes(bytes(changed))
        with self.assertRaises(R.Failed):  # one bit of the file
            R.verify_file(other, sig, *key, expect_name=False)
        lines = sig.splitlines()
        lines[2] = lines[2].replace("Vaelon-Setup-9.9.9.exe", "Vaelon-Setup-0.0.1.exe")
        with self.assertRaises(R.Failed):  # the trusted comment
            R.verify_file(self.file, "\n".join(lines) + "\n", *key)
        _, seed = R.open_secret(self.keyfile.read_text("ascii"), PASSWORD)
        with self.assertRaises(R.Failed):  # another key
            R.verify_file(self.file, R.sign_file(self.file, self.key_id, os.urandom(32)), *key)
        with self.assertRaises(R.Failed):  # another key id
            R.verify_file(self.file, R.sign_file(self.file, os.urandom(8), seed), *key)
        for broken in ("", "garbage", sig.replace("untrusted comment", "comment"), "\n".join(sig.splitlines()[:2])):
            with self.assertRaises(R.Failed):
                R.verify_file(self.file, broken, *key)

    def test_a_renamed_old_file_does_not_pass_for_a_new_one(self):  # rollback
        sig = self.sign().read_text("utf-8")
        renamed = self.files / "Vaelon-Setup-10.0.0.exe"
        shutil.copy(self.file, renamed)
        with self.assertRaises(R.Failed) as e:
            R.verify_file(renamed, sig, self.key_id, self.pub)
        self.assertIn("Vaelon-Setup-9.9.9.exe", str(e.exception))

    def test_a_legacy_unhashed_signature_is_refused(self):
        sig = self.sign().read_text("utf-8").splitlines()
        raw = base64.b64decode(sig[1])
        blake_file = self.files / "Vaelon-Setup-9.9.9.exe.blake"
        blake_file.write_bytes(hashlib.blake2b(self.file.read_bytes(), digest_size=64).digest())
        sig[1] = base64.b64encode(b"Ed" + raw[2:]).decode()
        with self.assertRaises(R.Failed):
            R.verify_file(blake_file, "\n".join(sig) + "\n", self.key_id, self.pub, expect_name=False)

    def test_a_non_ascii_name_signs_and_verifies(self):
        f = self.files / "Vaelon-Setup-9.9.9-ü.exe"
        f.write_bytes(b"x" * 1000)
        self.sign(f)
        R.verify_file(f, Path(f"{f}.minisig").read_text("utf-8"), self.key_id, self.pub)


class Draft(Base):
    def gh(self, draft=True, sums_ok=True, drafts=1, stray=False):
        calls = []
        payload = {"Vaelon-Setup-9.9.9.exe": os.urandom(5000), "Vaelon-9.9.9.dmg": os.urandom(4000)}
        sums = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in payload.items())
        if not sums_ok:
            sums = sums.replace(sums[:4], "0000", 1)

        def fake(*args):
            calls.append(args)
            if args[:2] == ("release", "list"):
                return json.dumps([{"tagName": "v9.9.9", "isDraft": True}] * drafts + [{"tagName": "v0.1.0"}])
            if args[:2] == ("release", "view"):
                names = list(payload) + ["SHA256SUMS.txt"]
                uploaded = getattr(self, "uploaded", [])
                assets = [{"name": n} for n in names + uploaded + (["Old.exe.minisig"] if stray else [])]
                return json.dumps({"isDraft": draft, "assets": assets, "url": "https://example.test/draft"})
            if args[:2] == ("release", "download"):
                folder = Path(args[args.index("--dir") + 1])
                for k, v in payload.items():
                    (folder / k).write_bytes(v)
                (folder / "SHA256SUMS.txt").write_text(sums, "utf-8")
                return ""
            if args[:2] == ("release", "upload"):
                self.uploaded = [Path(a).name for a in args if a.endswith(".minisig")]
                for a in args:
                    if a.endswith(".minisig"):
                        folder = Path(a).parent
                        name = Path(a).name[:-len(".minisig")]
                        R.verify_file(folder / name, Path(a).read_text("utf-8"), self.key_id, self.pub)
                return ""
            raise AssertionError(args)
        return fake, calls

    def test_the_draft_is_checked_signed_and_uploaded(self):
        fake, calls = self.gh()
        names = R.sign_draft("9.9.9", self.keyfile, gh=fake)
        self.assertEqual(sorted(names), ["SHA256SUMS.txt.minisig", "Vaelon-9.9.9.dmg.minisig",
                                         "Vaelon-Setup-9.9.9.exe.minisig"])
        self.assertEqual(sorted(self.uploaded), sorted(names))
        upload = next(c for c in calls if c[:2] == ("release", "upload"))
        self.assertIn("--clobber", upload)
        self.assertEqual(upload[2], "v9.9.9")

    def test_two_drafts_with_one_tag_are_refused(self):
        fake, calls = self.gh(drafts=2)
        with self.assertRaises(R.Failed):
            R.sign_draft("9.9.9", self.keyfile, gh=fake)
        self.assertFalse([c for c in calls if c[:2] == ("release", "upload")])

    def test_a_stray_signature_left_on_the_draft_is_reported(self):
        fake, _ = self.gh(stray=True)
        with self.assertRaises(R.Failed) as e:
            R.sign_draft("9.9.9", self.keyfile, gh=fake)
        self.assertIn("Old.exe.minisig", str(e.exception))

    def test_checksum_files_with_odd_lines_or_duplicates_are_refused(self):
        folder = self.dir / "sums"
        folder.mkdir()
        (folder / "a.exe").write_bytes(b"a")
        h = hashlib.sha256(b"a").hexdigest()
        for text in (f"{h}  a.exe\n{h}  a.exe\n", f"{h}  a.exe\nhello\n", f"{h}  a.exe\n{h}  b.exe\n", ""):
            (folder / "SHA256SUMS.txt").write_text(text, "utf-8")
            with self.assertRaises(R.Failed, msg=text):
                R.check_sums(folder)
        (folder / "SHA256SUMS.txt").write_text(f"{h}  a.exe\n", "utf-8")
        R.check_sums(folder)

    def test_a_published_release_or_bad_sums_are_not_signed(self):
        fake, calls = self.gh(draft=False)
        with self.assertRaises(R.Failed):
            R.sign_draft("9.9.9", self.keyfile, gh=fake)
        self.assertFalse([c for c in calls if c[:2] == ("release", "upload")])
        fake, calls = self.gh(sums_ok=False)
        with self.assertRaises(R.Failed):
            R.sign_draft("9.9.9", self.keyfile, gh=fake)
        self.assertFalse([c for c in calls if c[:2] == ("release", "upload")])
        with self.assertRaises(R.Failed):
            R.sign_draft("9.9.9; rm -rf /", self.keyfile, gh=fake)


class Repository(unittest.TestCase):
    def test_no_stray_control_characters_in_text_files(self):  # a "\v" once became a vertical tab in the docs
        bad = set(range(0, 9)) | {11, 12} | set(range(14, 32))
        found = []
        for pattern in ("*.md", "*.py", "*.yml", "*.ts", "*.tsx"):
            for p in ROOT.rglob(pattern):
                if any(part in ("node_modules", ".next", "out", "dist", "build", "versions") for part in p.parts):
                    continue
                if any(b in bad for b in p.read_bytes()):
                    found.append(str(p.relative_to(ROOT)))
        self.assertEqual(found, [])

    def test_ci_never_signs_or_holds_a_signing_key(self):
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = wf.read_text("utf-8")
            for word in ("RELEASE_SIGNING_KEY", "release_sign.py sign", "minisign -S", ".key"):
                self.assertNotIn(word, text.replace("sign-draft", ""), f"{wf.name}: {word}")


if __name__ == "__main__":
    unittest.main()
