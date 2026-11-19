"""Phone and email: set up from the app, encrypted contacts, the mail and Twilio calls (both replaced - nothing is sent)."""
import json
import os
import sys
import tempfile
import unittest

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import config, settings  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import comms, registry  # noqa: E402

registry.load_builtin()


def ctx(cfg=None, ok=True):
    asked = []
    c = registry.Ctx(cfg or Config(), approver=lambda r: asked.append(r.summary) or ok)
    c.asked = asked
    return c


class Contacts(unittest.TestCase):
    def setUp(self):
        for f in ("contacts.enc", "contacts.json"):
            (config.HOME / f).unlink(missing_ok=True)

    def test_saved_contacts_are_encrypted_and_can_be_undone(self):
        out = registry.execute(ctx(), "contact_save", {"name": "Mama", "phone": "+1 555 0100 123"})
        self.assertIn("saved Mama", out)
        raw = (config.HOME / "contacts.enc").read_text("utf-8")
        self.assertNotIn("Mama", raw)  # personal data: never in plain text on disk
        self.assertNotIn("359888123456", raw)
        registry.execute(ctx(), "contact_save", {"name": "Mama", "email": "mama@example.com"})  # adds, keeps the phone
        self.assertEqual(json.loads(registry.execute(ctx(), "contact_lookup", {"name": "mam"})),
                         {"Mama": {"phone": "+15550100123", "email": "mama@example.com"}})
        undo.undo()
        self.assertEqual(comms._contacts(), {"Mama": {"phone": "+15550100123"}})
        self.assertIn("deleted", registry.execute(ctx(), "contact_delete", {"name": "Mama"}))
        self.assertEqual(comms._contacts(), {})
        undo.undo()
        self.assertIn("Mama", comms._contacts())

    def test_bad_numbers_and_addresses_are_refused(self):
        for args in ({"name": "X", "phone": "05550100123"}, {"name": "X", "email": "not-an-address"}, {"name": "X"}):
            self.assertTrue(registry.execute(ctx(), "contact_save", args).startswith("ERROR"), args)
        self.assertEqual(comms._contacts(), {})

    def test_an_old_plain_contacts_file_is_moved_into_the_encrypted_store(self):
        (config.HOME / "contacts.json").write_text(json.dumps({"Ivan": {"phone": "+15550100111"}}), "utf-8")
        self.assertEqual(comms._contacts(), {"Ivan": {"phone": "+15550100111"}})
        self.assertFalse((config.HOME / "contacts.json").exists())
        self.assertTrue((config.HOME / "contacts.enc").exists())


class Sending(unittest.TestCase):
    def setUp(self):
        for k in ("VAELON_SMTP_USER", "VAELON_SMTP_PASS", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.setUp()

    def test_not_set_up_points_to_the_settings(self):
        c = ctx(Config())
        self.assertIn("Settings > Phone and email", registry.execute(c, "send_email", {"to": "a@b.cd", "subject": "s", "body": "b"}))
        self.assertIn("Settings > Phone and email", registry.execute(c, "send_sms", {"to": "+15550100123", "message": "hi"}))

    def test_email_goes_over_tls_and_port_465_uses_ssl_and_every_send_is_approved_first(self):
        import smtplib

        log = []

        class Fake:
            def __init__(self, host, port, timeout=0):
                log.append(("open", type(self).__name__, host, port))

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def starttls(self):
                log.append(("starttls",))

            def login(self, user, pw):
                log.append(("login", user))

            def send_message(self, m):
                log.append(("send", m["To"], m["Subject"]))

        class SMTP(Fake):
            pass

        class SMTP_SSL(Fake):
            pass

        real = smtplib.SMTP, smtplib.SMTP_SSL
        smtplib.SMTP, smtplib.SMTP_SSL = SMTP, SMTP_SSL
        os.environ["VAELON_SMTP_USER"], os.environ["VAELON_SMTP_PASS"] = "me@example.com", "app-password-0000001"
        try:
            c = ctx(Config(smtp_host="smtp.gmail.com", smtp_port=587))
            out = registry.execute(c, "send_email", {"to": "boss@example.com", "subject": "Report", "body": "Done."})
            self.assertEqual(out, "email sent to boss@example.com")
            self.assertIn("EMAIL to boss@example.com", c.asked[0])  # you saw it before it went
            self.assertEqual(log[:4], [("open", "SMTP", "smtp.gmail.com", 587), ("starttls",), ("login", "me@example.com"),
                                       ("send", "boss@example.com", "Report")])
            log.clear()
            registry.execute(ctx(Config(smtp_host="smtp.example.org", smtp_port=465)), "send_email", {"to": "x@example.org", "subject": "s", "body": "b"})
            self.assertEqual(log[0], ("open", "SMTP_SSL", "smtp.example.org", 465))
            self.assertNotIn(("starttls",), log)
            log.clear()
            self.assertTrue(registry.execute(ctx(Config(smtp_host="smtp.gmail.com"), ok=False), "send_email",
                                             {"to": "a@b.cd", "subject": "s", "body": "b"}).startswith("DENIED"))
            self.assertEqual(log, [])  # refused: nothing was even connected
        finally:
            smtplib.SMTP, smtplib.SMTP_SSL = real

    def test_sms_goes_to_twilio_from_your_number(self):
        sent = []

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"sid": "SM123"}

        real = comms.requests.post
        comms.requests.post = lambda url, **kw: sent.append((url, kw)) or R()
        os.environ.update(TWILIO_ACCOUNT_SID="AC" + "1" * 32, TWILIO_AUTH_TOKEN="t" * 32, TWILIO_FROM="+15550100")
        try:
            self.assertEqual(registry.execute(ctx(), "send_sms", {"to": "+15550100123", "message": "Running late"}),
                             "sms queued, sid=SM123")
        finally:
            comms.requests.post = real
        url, kw = sent[0]
        self.assertEqual(url, f"https://api.twilio.com/2010-04-01/Accounts/AC{'1' * 32}/Messages.json")
        self.assertEqual(kw["data"], {"To": "+15550100123", "From": "+15550100", "Body": "Running late"})


class SettingsScreen(unittest.TestCase):
    def setUp(self):
        for k in ("VAELON_SMTP_USER", "TWILIO_FROM"):
            (config.HOME / "secrets" / f"key_{k}").unlink(missing_ok=True)

    def test_email_and_phone_are_set_up_from_the_app(self):
        cfg = Config()
        self.assertEqual(settings.apply(cfg, {"mail_provider": "gmail"}), (["smtp_host", "smtp_port", "imap_host"], None))
        self.assertEqual((cfg.smtp_host, cfg.smtp_port, cfg.imap_host), ("smtp.gmail.com", 587, "imap.gmail.com"))
        self.assertEqual(settings.comms(cfg)["provider"], "gmail")
        for bad in ({"mail_provider": "hotmail.ru"}, {"smtp_host": "smtp gmail com"}, {"smtp_host": "a;rm -rf"}, {"smtp_port": 22}):
            self.assertIsNotNone(settings.apply(cfg, bad)[1], bad)
        self.assertEqual(settings.set_key("VAELON_SMTP_USER", "not-an-address"), "that is not an email address")
        self.assertIsNone(settings.set_key("VAELON_SMTP_USER", "me@example.com"))
        self.assertIsNone(settings.set_key("TWILIO_FROM", "+1 555 0100 123"))
        self.assertEqual(config.env("TWILIO_FROM"), "+15550100123")  # spaces removed: the number Twilio expects
        self.assertEqual(settings.set_key("TWILIO_FROM", "555 0100 123"), "the number must be in international form, e.g. +15550100123")
        rows = {k["name"]: k for k in settings.keys()}
        self.assertTrue(rows["VAELON_SMTP_USER"]["set"])
        self.assertNotIn("me@example.com", json.dumps(settings.snapshot(cfg)))  # shown as "set" only


if __name__ == "__main__":
    unittest.main()
