"""The winget update script (issue #26): manifests filled correctly, odd input refused, the installer's SHA-256 taken
only when GitHub's digest and SHA256SUMS.txt both exist and agree, the right action chosen, and the pull request made
of exactly the three files. No network: GitHub is a stand-in that records every request."""
import base64
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import winget_update as W  # noqa: E402

SHA = "f21a0e0dca3c46aa6e4cefc51070050dd2b9a99702f9c74aa4f15908e9259afb"


def release(digest=f"sha256:{SHA}", draft=False, pre=False):
    return {"draft": draft, "prerelease": pre, "published_at": "2026-12-01T10:00:00Z",
            "assets": [{"name": "Vaelon-Setup-0.20.0.exe", "digest": digest}, {"name": "SHA256SUMS.txt"}]}


class Fake:
    """Stand-in for W.Http: answers from a table keyed by (method, path prefix) and records every call."""

    def __init__(self, routes=None, sums=f"{SHA}  Vaelon-Setup-0.20.0.exe\n{'0' * 64}  Vaelon-0.20.0.dmg\n"):
        self.routes, self.sums, self.calls = routes or {}, sums, []

    def request(self, method, url, json_body=None):
        assert url.startswith(W.API)
        path = url[len(W.API):]
        self.calls.append((method, path, json_body))
        for (m, prefix), (code, data) in self.routes.items():
            if m == method and path.startswith(prefix):
                return W.Answer(code, json.dumps(data).encode())
        return W.Answer(404, b"")

    def download(self, url):
        assert url.startswith(W.DOWNLOADS)
        return W.Answer(200, self.sums.encode())


def gh(version_dirs, found, branch_code=201):
    """A GitHub that already holds `version_dirs` of the package and these open PRs."""
    return Fake({
        ("GET", "repos/microsoft/winget-pkgs/git/ref/"): (200, {"object": {"sha": "up1"}}),
        ("GET", "repos/microsoft/winget-pkgs/contents/"): (200, [{"name": v} for v in version_dirs]) if version_dirs
        else (404, {}),
        ("GET", "repos/microsoft/winget-pkgs"): (200, {"default_branch": "master"}),
        ("GET", "search/issues"): (200, {"items": found}),
        ("POST", "repos/Nokk1251/winget-pkgs/git/refs"): (branch_code, {}),
        ("GET", "repos/Nokk1251/winget-pkgs/git/ref/"): (200, {"object": {"sha": "old"}}),
        ("PATCH", "repos/Nokk1251/winget-pkgs/git/refs/"): (200, {}),
        ("POST", "repos/Nokk1251/winget-pkgs/git/blobs"): (201, {"sha": "b"}),
        ("GET", "repos/Nokk1251/winget-pkgs/git/commits/"): (200, {"tree": {"sha": "t0"}}),
        ("POST", "repos/Nokk1251/winget-pkgs/git/trees"): (201, {"sha": "t1"}),
        ("POST", "repos/Nokk1251/winget-pkgs/git/commits"): (201, {"sha": "c1"}),
        ("POST", "repos/microsoft/winget-pkgs/pulls"): (201, {"html_url": "https://github.com/microsoft/winget-pkgs/pull/9"}),
    })


class Render(unittest.TestCase):
    def test_three_manifests_with_every_placeholder_filled(self):
        files = W.render("v0.20.0", SHA, "2026-12-01")
        self.assertEqual(sorted(files), ["Nokk_7.Vaelon.installer.yaml", "Nokk_7.Vaelon.locale.en-US.yaml",
                                         "Nokk_7.Vaelon.yaml"])
        inst = files["Nokk_7.Vaelon.installer.yaml"]
        self.assertIn("PackageVersion: 0.20.0", inst)
        self.assertIn("releases/download/v0.20.0/Vaelon-Setup-0.20.0.exe", inst)
        self.assertEqual(inst.count(SHA.upper()), 2)
        self.assertIn("ReleaseDate: 2026-12-01", inst)
        self.assertFalse(any("{{" in t for t in files.values()))

    def test_odd_input_is_refused(self):
        for bad in ("0.20", "0.20.0; rm -rf /", "../0.20.0", "0.20.0\nx", "v1.2.3.4", ""):
            with self.assertRaises(W.Failed, msg=bad):
                W.render(bad, SHA, "2026-12-01")
        with self.assertRaises(W.Failed):
            W.render("0.20.0", "not-a-hash", "2026-12-01")
        with self.assertRaises(W.Failed):
            W.render("0.20.0", SHA, "tomorrow")

    def test_the_templates_give_exactly_the_submitted_0_19_0_package(self):  # microsoft/winget-pkgs#489220
        files = W.render("0.19.0", "F21A0E0DCA3C46AA6E4CEFC51070050DD2B9A99702F9C74AA4F15908E9259AFB", "2026-11-23")
        inst = files["Nokk_7.Vaelon.installer.yaml"]
        for line in ("InstallerType: inno", "Custom: /ALLUSERS", "Custom: /CURRENTUSER", "Scope: machine", "Scope: user",
                     "ProductCode: '{6B1E0C52-7C0E-4D0B-9A53-3A6D8B1F0E21}_is1'", "ReleaseDate: 2026-11-23"):
            self.assertIn(line, inst)
        self.assertIn("ManifestVersion: 1.28.0", files["Nokk_7.Vaelon.yaml"])
        self.assertIn("License: GPL-3.0-or-later", files["Nokk_7.Vaelon.locale.en-US.yaml"])


class Checksum(unittest.TestCase):
    def fake(self, rel, **kw):
        return Fake({("GET", "repos/Nokk1251/vaelon/releases/tags/"): (200, rel)}, **kw)

    def test_digest_and_sums_must_agree(self):
        self.assertEqual(W.installer_sha(self.fake(release()), "0.20.0"), (SHA.upper(), "2026-12-01"))
        with self.assertRaises(W.Failed):
            W.installer_sha(self.fake(release(digest="sha256:" + "1" * 64)), "0.20.0")

    def test_no_digest_no_update(self):
        for d in ("", None, SHA, "md5:abc"):
            with self.assertRaises(W.Failed, msg=d):
                W.installer_sha(self.fake(release(digest=d)), "0.20.0")

    def test_drafts_pre_releases_and_missing_files_are_refused(self):
        for rel in (release(draft=True), release(pre=True), {"draft": False, "assets": []}):
            with self.assertRaises(W.Failed):
                W.installer_sha(self.fake(rel), "0.20.0")

    def test_a_sums_line_for_another_file_does_not_count(self):
        with self.assertRaises(W.Failed):
            W.installer_sha(self.fake(release(), sums=f"{SHA}  not-Vaelon-Setup-0.20.0.exe\n"), "0.20.0")


class Plan(unittest.TestCase):
    def pr(self, title, who="Nokk1251"):
        return {"title": title, "user": {"login": who}, "html_url": f"https://x/{title[-6:]}"}

    def test_what_to_do(self):
        P = W.plan
        self.assertEqual(P("0.20.0", ["0.19.0"], []), ("send", "Update: Nokk_7.Vaelon to 0.20.0"))
        self.assertEqual(P("0.19.0", [], []), ("send", "New package: Nokk_7.Vaelon version 0.19.0"))
        self.assertEqual(P("0.20.0", ["0.19.0"], [self.pr("Update: Nokk_7.Vaelon to 0.20.0")])[0], "open")
        self.assertEqual(P("0.20.0", ["0.19.0"], [self.pr("Update: Nokk_7.Vaelon to 0.20.0", "someone")])[0], "stop")
        self.assertEqual(P("0.20.0", ["0.19.0", "0.20.0"], [])[0], "stop")  # already in winget
        # the first submission (0.19.0) still waits: no second "New package"
        self.assertEqual(P("0.20.0", [], [self.pr("New package: Nokk_7.Vaelon version 0.19.0")])[0], "stop")

    def test_a_version_is_matched_whole(self):  # 0.2.0 must not be taken for 0.20.0
        self.assertEqual(W.plan("0.2.0", ["0.1.0"], [self.pr("Update: Nokk_7.Vaelon to 0.20.0")])[0], "send")


class Submit(unittest.TestCase):
    def test_an_update_is_three_files_in_the_right_folder_by_nokk_7(self):
        s = gh(["0.19.0"], [])
        url = W.submit(s, "0.20.0", W.render("0.20.0", SHA, "2026-12-01"))
        self.assertEqual(url, "https://github.com/microsoft/winget-pkgs/pull/9")
        tree = next(b for m, p, b in s.calls if p.endswith("git/trees"))["tree"]
        self.assertEqual(sorted(x["path"] for x in tree), [
            "manifests/n/Nokk_7/Vaelon/0.20.0/Nokk_7.Vaelon.installer.yaml",
            "manifests/n/Nokk_7/Vaelon/0.20.0/Nokk_7.Vaelon.locale.en-US.yaml",
            "manifests/n/Nokk_7/Vaelon/0.20.0/Nokk_7.Vaelon.yaml"])
        commit = next(b for m, p, b in s.calls if m == "POST" and p.endswith("git/commits"))
        self.assertEqual((commit["author"]["name"], commit["message"]), ("Nokk_7", "Update: Nokk_7.Vaelon to 0.20.0"))
        self.assertTrue(commit["author"]["email"].endswith("@users.noreply.github.com"))
        pr = next(b for m, p, b in s.calls if p.endswith("/pulls"))
        self.assertEqual((pr["head"], pr["base"]), ("Nokk1251:Nokk_7.Vaelon-0.20.0", "master"))
        blobs = [base64.b64decode(b["content"]).decode() for m, p, b in s.calls if p.endswith("git/blobs")]
        self.assertTrue(all("0.20.0" in x for x in blobs))

    def test_an_open_pr_of_ours_is_returned_and_nothing_is_written(self):
        s = gh(["0.19.0"], [{"title": "Update: Nokk_7.Vaelon to 0.20.0", "user": {"login": "Nokk1251"},
                             "html_url": "https://github.com/microsoft/winget-pkgs/pull/5"}])
        self.assertEqual(W.submit(s, "0.20.0", {}), "https://github.com/microsoft/winget-pkgs/pull/5")
        self.assertFalse([c for c in s.calls if c[0] != "GET"])

    def test_a_branch_left_from_before_is_reset_to_upstream(self):
        s = gh(["0.19.0"], [], branch_code=422)
        W.submit(s, "0.20.0", W.render("0.20.0", SHA, "2026-12-01"))
        patches = [b for m, p, b in s.calls if m == "PATCH"]
        self.assertEqual(patches[0], {"sha": "up1", "force": True})

    def test_a_bad_token_stops_at_once_with_a_clear_reason(self):
        s = gh(["0.19.0"], [])
        s.routes[("POST", "repos/Nokk1251/winget-pkgs/git/refs")] = (403, {})
        with self.assertRaises(W.Failed) as e:
            W.submit(s, "0.20.0", W.render("0.20.0", SHA, "2026-12-01"))
        self.assertIn("public_repo", str(e.exception))
        self.assertEqual(sum(1 for c in s.calls if c[1].endswith("git/refs")), 1)  # no retries


class Main(unittest.TestCase):
    def setUp(self):
        self.real = (W.Http, W.submit)
        self.sent = []
        W.Http = lambda token: Fake({("GET", "repos/Nokk1251/vaelon/releases/tags/"): (200, release())})
        W.submit = lambda *a: self.sent.append(a) or "url"
        self.old = os.environ.pop("WINGET_TOKEN", None)

    def tearDown(self):
        W.Http, W.submit = self.real
        if self.old is not None:
            os.environ["WINGET_TOKEN"] = self.old

    def test_without_the_token_nothing_is_sent(self):
        self.assertEqual(W.main(["0.20.0"]), 0)
        self.assertEqual(self.sent, [])

    def test_an_unknown_flag_sends_nothing(self):  # "--dryrun" must never become a real run
        os.environ["WINGET_TOKEN"] = "test-not-a-real-token"
        try:
            self.assertEqual(W.main(["0.20.0", "--dryrun"]), 2)
            self.assertEqual(self.sent, [])
        finally:
            os.environ.pop("WINGET_TOKEN", None)

    def test_the_token_is_never_sent_outside_the_api(self):
        h = self.real[0]("test-not-a-real-token")
        with self.assertRaises(W.Failed):
            h.request("GET", "https://evil.example/x")
        with self.assertRaises(W.Failed):
            h.download("https://evil.example/SHA256SUMS.txt")


if __name__ == "__main__":
    unittest.main()
