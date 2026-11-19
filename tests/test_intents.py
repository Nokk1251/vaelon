"""Direct intents, user profile, persistent conversation, Voice Designer, catalog (offline: sources are faked)."""
import os
import sys
import tempfile
import types
import unittest

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import conversation, intents, profile  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.memory import Memory  # noqa: E402


def fake_sources():
    K = types.SimpleNamespace()
    K.resolve_ticker = lambda name: "XYZ"
    K.stock_history = lambda sym, n: {"symbol": sym, "name": "Nvidia Corp", "currency": "USD", "price": 110.0,
                                      "closes": [("01.11", 100.0), ("02.11", 105.0), ("03.11", 108.0), ("04.11", 110.0)]}

    def _get(url, params=None, **kw):
        if "coingecko" in url:
            return {"bitcoin": {"usd": 70000.0, "eur": 64000.0, "usd_24h_change": 1.5}}
        if "frankfurter" in url:
            return {"rates": {"USD": 1.1}, "date": "2026-11-06"}
        raise AssertionError(url)

    K._get = _get
    K.weather_data = lambda place, lang: {"place": place, "country": "България", "now": {
        "temperature_2m": 10, "apparent_temperature": 8, "wind_speed_10m": 5, "weather_code": 0},
        "daily": {"temperature_2m_min": [1, 2, 3], "temperature_2m_max": [9, 10, 11],
                  "precipitation_probability_max": [0, 10, 20], "weather_code": [0, 3, 61]}}
    return K


class Intents(unittest.TestCase):
    def setUp(self):
        self.K = fake_sources()

    def test_stock_in_bulgarian(self):
        out = intents._stock("Как вървят акциите на Nvidia последните 3 дни?", True, self.K)
        self.assertIn("NVDA", out)
        self.assertIn("последни 3", out)
        self.assertIn("+10.00%", out)  # 100 -> 110
        self.assertIn("не инвестиционен съвет", out)

    def test_company_suffix_and_false_positive(self):
        self.assertEqual(intents._ticker("Как е Теслата днес?", self.K), "TSLA")
        self.assertNotEqual(intents._ticker("акции на металургични фирми", self.K), "META")

    def test_crypto_and_fx(self):
        self.assertIn("70 000.00 USD", intents._crypto("колко струва биткойн", True, self.K))
        self.assertIsNone(intents._crypto("какво е биткойн", True, self.K))  # definition -> encyclopedia
        self.assertIn("195.58 BGN", intents._fx("колко са 100 евро в лева", True, self.K))
        self.assertIn("1.1000 USD", intents._fx("курс на еврото към долара", True, self.K))
        self.assertIsNone(intents._fx("Колко евро струва iPhone?", True, self.K))

    def test_weather(self):
        out = intents._weather("Какво е времето във Варна?", True, self.K)
        self.assertTrue(out.startswith("Варна"))
        self.assertIn("Утре", out)

    def test_wiki_prefetch_and_help(self):
        h = intents.detect("Какво е черна дупка?")
        self.assertEqual((h.tool, h.args["lang"]), ("wiki", "bg"))
        self.assertIn("☰", intents.detect("помощ").answer)
        self.assertIsNone(intents.detect("Напиши ми стихотворение за морето"))

    def test_comparisons_go_to_the_model(self):
        # one live source cannot answer "compare A and B": the model must look both up (it can do so in parallel)
        self.assertIsNone(intents.detect("Compare the weather in Sofia and Varna right now"))
        self.assertIsNone(intents.detect("Сравни времето в София и Варна"))
        self.assertTrue(intents.COMPARE_RX.search("Nvidia vs AMD stock"))
        self.assertFalse(intents.COMPARE_RX.search("What is the weather in Varna?"))

    def test_remember_and_about_me(self):
        m = Memory(":memory:")
        self.assertIn("Запомних", intents.detect("запомни, че рожденият ми ден е на 13 юли", m).answer)
        profile.observe("Казвам се Ники и живея в Пловдив")
        about = intents.detect("какво знаеш за мен", m).answer
        self.assertIn("Ники", about)
        self.assertIn("13 юли", about)


class Continuity(unittest.TestCase):
    def test_profile_is_encrypted_and_picks_facts(self):
        profile.wipe()
        changed = profile.observe("Здрасти, казвам се Мария, работя като лекар и обичам планините")
        self.assertEqual(changed["name"], "Мария")
        self.assertIn("лекар", changed["job"])
        raw = (profile.config.HOME / profile.FILE).read_text("utf-8")
        self.assertNotIn("Мария", raw)  # encrypted at rest
        self.assertEqual(profile.observe("аз съм уморен"), {})  # lowercase is not a name

    def test_conversation_survives_restart_encrypted(self):
        from vaelon.agent import Agent
        from vaelon.llm import MockLLM

        conversation.clear()
        a = Agent(Config(provider="mock"), llm=MockLLM(['{"final": "Здравей."}']), memory=Memory(":memory:"),
                  load_extensions=False)
        a.persist, a.use_intents = True, False
        a.run("Здравей")
        raw = conversation.path().read_text("utf-8")
        self.assertNotIn("Здравей", raw)
        self.assertEqual([m["content"] for m in conversation.load()], ["Здравей", "Здравей."])
        conversation.clear()
        self.assertEqual(conversation.load(), [])

    def test_bulgarian_reply_hint(self):
        from vaelon.agent import Agent
        from vaelon.llm import MockLLM

        llm = MockLLM(['{"final": "ok"}'])
        Agent(Config(provider="mock"), llm=llm, memory=Memory(":memory:"), load_extensions=False).run("Напиши ми нещо")
        self.assertIn("REPLY IN BULGARIAN", llm.seen[0][-1]["content"])


class Voice(unittest.TestCase):
    def test_normalize_clamps(self):
        from vaelon import tts

        v = tts.normalize({"preset": "titan", "pitch": 9, "echo": -1, "metal": "x"})
        self.assertEqual((v["pitch"], v["echo"], v["metal"]), (1.5, 0.0, tts.PRESETS["titan"]["metal"]))
        self.assertEqual(tts.normalize({"preset": "nope"})["preset"], "vaelon")

    def test_design_runs(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        from vaelon import tts

        x = np.sin(np.linspace(0, 200, 22050)).astype(np.float32)
        for name in tts.PRESETS:
            y = tts.design(x, 22050, tts.normalize({"preset": name}))
            self.assertLessEqual(float(np.max(np.abs(y))), 0.91)


class Catalog(unittest.TestCase):
    def test_catalog_lists_everything(self):
        from vaelon import catalog

        c = catalog.build(Memory(":memory:"))
        names = {t["name"] for t in c["tools"]}
        self.assertTrue({"stock_quote", "weather", "fs_list", "web_search"} <= names)
        self.assertGreaterEqual(len(c["skills"]), 21)
        self.assertIn("GROQ_API_KEY", c["keys"])
        self.assertTrue(c["examples"])


class HistoryHygiene(unittest.TestCase):
    def test_unanswered_and_failed_turns_are_dropped(self):
        from vaelon.agent import _pairs

        h = [{"role": "user", "content": "Search Python version"}, {"role": "assistant", "content": "3.15.2"},
             {"role": "user", "content": "What is the stock market doing?"},  # its answer was empty: dropped
             {"role": "user", "content": "Hello?"},
             {"role": "assistant", "content": "I could not reach any language model: HTTP 400"}]  # failure: dropped
        self.assertEqual([m["content"] for m in _pairs(h)], ["Search Python version", "3.15.2"])


class ReplyLanguage(unittest.TestCase):
    def test_detection(self):
        self.assertEqual(intents.lang_of("Can you recommend the best laptops of 2026?"), "en")
        self.assertEqual(intents.lang_of("Кои са най-добрите лаптопи?"), "bg")
        self.assertIsNone(intents.lang_of("Hier sind fünf aktuelle Laptops, die sehr gut sind"))

    def test_german_answer_to_english_question_is_translated(self):
        from vaelon.agent import Agent

        class L:
            def chat(self, messages):
                if "Translate" in messages[0]["content"]:
                    return "Here are five current laptops that are very good."
                return "Hier sind fünf aktuelle Laptops, die sehr gut sind und in der Regel unter 1500 liegen."

        a = Agent(Config(provider="mock"), llm=L(), memory=Memory(":memory:"), load_extensions=False)
        self.assertTrue(a.run("Can you recommend the best laptops of 2026?").startswith("Here are"))


class SkillMatching(unittest.TestCase):
    def test_triggers_need_a_word_start(self):
        from vaelon import skills

        s = skills.load_all()
        names = lambda q: [k.name for k in skills.match(q, s)]  # noqa: E731
        self.assertNotIn("phone-call", names("Кой телефон да си купя?"))  # buying a phone is not a call
        self.assertNotIn("phone-call", names("recall my notes"))  # 'call' inside 'recall'
        self.assertIn("phone-call", names("Обади се на мама"))
        self.assertIn("learning-coach", names("Научи ме на Python"))


class Microphone(unittest.TestCase):
    def test_wav_is_decoded_without_ffmpeg(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        import io
        import wave

        from vaelon import stt

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes((np.sin(np.linspace(0, 300, 48000)) * 8000).astype(np.int16).tobytes())
        x = stt._wav_to_16k(buf.getvalue())
        self.assertAlmostEqual(len(x), 16000, delta=2)  # 1 s at 16 kHz
        self.assertIsNone(stt._wav_to_16k(b"not a wav"))

    def test_groq_only_when_it_is_already_the_provider(self):
        from vaelon import stt

        local = Config(provider="ollama")
        self.assertNotEqual(stt.engine(local), "groq")  # a local user never has audio sent to a cloud


if __name__ == "__main__":
    unittest.main()
