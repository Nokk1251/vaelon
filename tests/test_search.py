"""Web search: the chain of sources, their hand-over, freshness and the ordering of results.
Offline: every source is replaced; request shapes follow the services' documentation (checked 2026-11-12)."""
import os
import sys
import tempfile
import unittest

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests  # noqa: E402

from vaelon import providers, search as S  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.tools import registry, web  # noqa: E402


def rows(*hosts):
    return [S._row(f"Result {i} about quantum computers", f"https://{h}/page{i}", "quantum computers explained") for i, h in enumerate(hosts)]


class Chain(unittest.TestCase):
    def setUp(self):
        self.real = S.SOURCES
        self.asked = []
        for k in (S.TAVILY_KEY, S.BRAVE_KEY):
            os.environ.pop(k, None)

    def tearDown(self):
        S.SOURCES = self.real
        for k in (S.TAVILY_KEY, S.BRAVE_KEY):
            os.environ.pop(k, None)

    def use(self, **behaviour):
        def make(name):
            def fn(query, limit, lang, fresh, key=""):
                self.asked.append((name, fresh, key))
                got = behaviour.get(name, [])
                if isinstance(got, Exception):
                    raise got
                return got(fresh) if callable(got) else got
            return fn

        S.SOURCES = (("Tavily", S.TAVILY_KEY, make("tavily")), ("Brave Search", S.BRAVE_KEY, make("brave")),
                     ("web search", "", make("meta")), ("Wikipedia", "", make("wiki")))

    def test_without_keys_the_public_engines_answer_and_wikipedia_backs_them_up(self):
        self.use(meta=rows("a.com", "b.com"), wiki=rows("en.wikipedia.org"))
        got, source = S.search("quantum computers", 6, "en")
        self.assertEqual((len(got), source), (2, "web search"))
        self.assertEqual([a[0] for a in self.asked], ["meta"])  # no key: the keyed services are not even tried
        self.asked.clear()
        self.use(meta=S.Unavailable("throttled"), wiki=rows("en.wikipedia.org"))
        got, source = S.search("quantum computers", 6, "en")
        self.assertEqual((len(got), source), (1, "Wikipedia"))
        self.use(meta=requests.ConnectionError("offline"), wiki=requests.ConnectionError("offline"))
        self.assertEqual(S.search("quantum computers"), ([], ""))
        self.assertEqual(S.search("   "), ([], ""))

    def test_a_key_puts_the_official_service_first_and_failures_hand_over(self):
        os.environ[S.TAVILY_KEY] = "tvly-test-key-00000001"
        os.environ[S.BRAVE_KEY] = "brave-test-key-0000001"
        self.use(tavily=rows("t.com"), brave=rows("b.com"), meta=rows("m.com"))
        self.assertEqual(S.search("quantum computers")[1], "Tavily")
        self.assertEqual(self.asked, [("tavily", "", "tvly-test-key-00000001")])
        self.asked.clear()
        self.use(tavily=S.Unavailable("HTTP 432"), brave=[], meta=rows("m.com"))  # out of credits, then nothing found
        self.assertEqual(S.search("quantum computers")[1], "web search")
        self.assertEqual([a[0] for a in self.asked], ["tavily", "brave", "meta"])
        self.assertEqual(S.sources()[:2], ["Tavily", "Brave Search"])

    def test_recent_questions_ask_for_recent_results_and_fall_back_when_there_are_none(self):
        self.assertEqual([S.freshness(q) for q in ("news about SpaceX today", "какво стана днес в София", "latest news on AI",
                                                    "новини за изборите", "latest Python release version", "history of Rome")],
                         ["d", "d", "w", "w", "", ""])
        self.use(meta=lambda fresh: rows("a.com", "b.com", "c.com") if fresh else rows("old.com"))
        got, _ = S.search("SpaceX news today")
        self.assertEqual((len(got), self.asked), (3, [("meta", "d", "")]))
        self.asked.clear()
        self.use(meta=lambda fresh: rows("a.com") if fresh else rows("x.com", "y.com", "z.com", "w.com"))
        got, _ = S.search("SpaceX news today")  # one fresh hit is too thin: look again without the time limit
        self.assertEqual(([a[1] for a in self.asked], len(got)), (["d", ""], 4))

    def test_results_are_deduplicated_spread_over_sites_and_ordered_by_match(self):
        raw = [S._row("Shop cheap things", "https://spam.example/a", "buy now"),
               S._row("Quantum computers", "https://www.site.org/q?utm_source=x", "what quantum computers are"),
               S._row("Quantum computers again", "https://site.org/q#top", "duplicate of the same page"),
               S._row("More quantum", "https://site.org/2", "quantum computers"),
               S._row("Even more quantum", "https://site.org/3", "quantum computers"),
               S._row("", "https://empty.example/", ""),
               S._row("No link", "", "quantum computers"),
               S._row("<b>Quantum</b>   computing\n basics", "https://uni.edu/qc", "an <i>intro</i> to quantum computers")]
        got = S.rank(raw, "what are quantum computers", 6)
        self.assertEqual([r["href"] for r in got], ["https://www.site.org/q?utm_source=x", "https://site.org/2", "https://uni.edu/qc",
                                                    "https://spam.example/a"])
        self.assertEqual(got[2]["title"], "Quantum computing basics")  # markup and line breaks are gone
        self.assertEqual(len(S.rank(rows(*["s%d.com" % i for i in range(20)]), "quantum", 6)), 6)
        videos = [S._row("Video a", "https://video.example/watch?v=a", "x"), S._row("Video b", "https://video.example/watch?v=b", "x")]
        self.assertEqual(len(S.rank(videos, "video", 6)), 2)  # a different ?v= is a different page

    def test_the_tool_names_its_source_and_admits_when_nothing_answered(self):
        registry.load_builtin()
        self.use(meta=[S._row("Python 3.15", "https://python.org/downloads", "the latest release", "2026-10-07T00:00:00")])
        ctx = registry.Ctx(Config())
        out = registry.execute(ctx, "web_search", {"query": "latest python"})
        self.assertIn('<untrusted_data source="web_search via web search">', out)
        self.assertIn("Python 3.15 - https://python.org/downloads (2026-10-07)", out)
        self.assertTrue(ctx.tainted)
        self.use(meta=S.Unavailable("throttled"), wiki=S.Unavailable("offline"))
        out = registry.execute(registry.Ctx(Config()), "web_search", {"query": "something else entirely"})
        self.assertTrue(out.startswith("ERROR: no search engine answered"))
        self.assertIn("do not answer from memory", out)
        self.use(meta=rows("a.com", "b.com"))
        self.assertEqual([r["href"] for r in web.search_results("quantum computers", 6, "bg-bg")],
                         ["https://a.com/page0", "https://b.com/page1"])  # research and learning use this form


class Wire(unittest.TestCase):
    """What is really sent to the keyed services (the network call itself is replaced)."""

    def setUp(self):
        self.sent = []
        self.real_get, self.real_post = requests.get, requests.post

        class R:
            status_code = 200

            def __init__(self, body):
                self._body = body

            def json(self):
                return self._body

        def post(url, **kw):
            self.sent.append(("POST", url, kw))
            return R({"results": [{"title": "T", "url": "https://t.example/1", "content": "found", "published_date": "2026-11-12"}]})

        def get(url, **kw):
            self.sent.append(("GET", url, kw))
            return R({"web": {"results": [{"title": "B", "url": "https://b.example/1", "description": "<strong>found</strong>"}]}})

        requests.post, requests.get = post, get

    def tearDown(self):
        requests.get, requests.post = self.real_get, self.real_post

    def test_tavily_and_brave_requests(self):
        got = S.tavily("spacex news", 5, "en", "d", "tvly-secret-000000000001")
        self.assertEqual((got[0]["href"], got[0]["date"]), ("https://t.example/1", "2026-11-12"))
        _, url, kw = self.sent[-1]
        self.assertEqual(url, "https://api.tavily.com/search")
        self.assertEqual(kw["json"], {"query": "spacex news", "max_results": 5, "search_depth": "basic", "time_range": "day",
                                      "topic": "news"})
        self.assertEqual(kw["headers"]["Authorization"], "Bearer tvly-secret-000000000001")
        self.assertFalse(kw["allow_redirects"])
        self.assertNotIn("time_range", (S.tavily("x", 5, "en", "", "k" * 20), self.sent[-1][2]["json"])[1])
        got = S.brave("новини", 4, "bg", "w", "brave-secret-00000000001")
        self.assertEqual((got[0]["href"], got[0]["body"]), ("https://b.example/1", "found"))
        _, url, kw = self.sent[-1]
        self.assertEqual(url, "https://api.search.brave.com/res/v1/web/search")
        self.assertEqual(kw["params"], {"q": "новини", "count": 4, "search_lang": "bg", "freshness": "pw"})
        self.assertEqual(kw["headers"]["X-Subscription-Token"], "brave-secret-00000000001")
        self.assertNotIn("brave-secret", str(kw["params"]) + url)  # the key is never part of the address
        for name, host in ((S.TAVILY_KEY, "api.tavily.com"), (S.BRAVE_KEY, "api.search.brave.com")):
            self.assertEqual(providers.KEY_HOSTS[name], host)
            self.assertIn(name, providers.EXTRA_KEYS)


if __name__ == "__main__":
    unittest.main()
