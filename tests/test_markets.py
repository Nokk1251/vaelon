"""Stock data sources: Twelve Data and Finnhub with the user's keys, Yahoo as the keyless fallback.
Offline: `market_data._call` is replaced; the answers are shaped like the real services' (checked 2026-11-12)."""
import os
import sys
import tempfile
import unittest

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import intents, market_data as M, providers  # noqa: E402
from vaelon.tools import knowledge as K  # noqa: E402

TD_SERIES = {"meta": {"symbol": "AAPL", "interval": "1day", "currency": "USD", "exchange": "NASDAQ"},
             "values": [{"datetime": "2026-11-06", "close": "342.37000"}, {"datetime": "2026-11-09", "close": "350.69000"},
                        {"datetime": "2026-11-10", "close": "348.51001"}, {"datetime": "2026-11-11", "close": "355.63000"}],
             "status": "ok"}
TD_QUOTE = {"symbol": "AAPL", "name": "Apple Inc.", "close": "356.10000", "previous_close": "348.51001"}
TD_SEARCH = {"data": [
    {"symbol": "4NVDA", "instrument_name": "NVIDIA", "exchange": "MTA", "instrument_type": "Common Stock", "country": "Italy"},
    {"symbol": "11090", "instrument_name": "Warrant on NVIDIA", "exchange": "HKEX", "instrument_type": "Warrant",
     "country": "Hong Kong"},
    {"symbol": "NVDA", "instrument_name": "NVIDIA Corp", "exchange": "NASDAQ", "instrument_type": "Common Stock",
     "country": "United States"}], "status": "ok"}
FH_QUOTE = {"c": 356.1, "d": 7.59, "dp": 2.18, "h": 357.0, "l": 349.3, "o": 349.5, "pc": 348.51, "t": 1794430740}
YAHOO = {"chart": {"result": [{"meta": {"longName": "Apple Inc.", "currency": "USD", "regularMarketPrice": 356.0,
                                        "gmtoffset": -18000},
                               "timestamp": [1794234600, 1794321000, 1794407400],
                               "indicators": {"quote": [{"close": [350.69, 348.51, 355.63]}]}}]}}


class Sources(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.answers = {}
        self.real = M._call

        def fake(url, params, headers=None):
            self.calls.append((url, dict(params), dict(headers or {})))
            for part, answer in self.answers.items():
                if part in url:
                    if isinstance(answer, Exception):
                        raise answer
                    return answer
            raise M.Unavailable("not scripted")

        M._call = fake
        for k in (M.TD_KEY, M.FH_KEY):
            os.environ.pop(k, None)

    def tearDown(self):
        M._call = self.real
        for k in (M.TD_KEY, M.FH_KEY):
            os.environ.pop(k, None)

    def test_without_keys_only_yahoo_is_asked(self):
        self.answers = {"finance/chart": YAHOO}
        h = M.history("aapl", 2)
        self.assertEqual((h["source"], h["name"], h["price"]), ("Yahoo Finance", "Apple Inc.", 356.0))
        self.assertEqual([c for _, c in h["closes"]], [350.69, 348.51, 355.63])
        self.assertTrue(all("yahoo" in url for url, _, _ in self.calls))
        self.assertEqual(M.sources(), ["Yahoo Finance"])

    def test_twelve_data_is_preferred_and_the_key_travels_in_a_header(self):
        os.environ[M.TD_KEY] = "td-test-key-0000000001"
        self.answers = {"/time_series": TD_SERIES, "/quote": TD_QUOTE}
        h = M.history("AAPL", 3)
        self.assertEqual((h["source"], h["name"], h["price"], h["currency"]), ("Twelve Data", "Apple Inc.", 356.1, "USD"))
        self.assertEqual(h["closes"], [("06.11", 342.37), ("09.11", 350.69), ("10.11", 348.51), ("11.11", 355.63)])
        url, params, headers = self.calls[0]
        self.assertEqual((params["outputsize"], params["order"], params["interval"]), (4, "asc", "1day"))
        self.assertEqual(headers, {"Authorization": "apikey td-test-key-0000000001"})
        self.assertFalse(any("td-test-key" in u or "td-test-key" in str(p) for u, p, _ in self.calls))  # never in the address
        self.assertEqual(M.sources(), ["Twelve Data", "Yahoo Finance"])

    def test_symbols_are_translated_for_twelve_data(self):
        os.environ[M.TD_KEY] = "td-test-key-0000000001"
        self.answers = {"/time_series": TD_SERIES, "/quote": M.Unavailable("no credit left")}
        self.assertEqual(M.history("^GSPC", 1)["symbol"], "^GSPC")  # asked as SPX, reported as the user knows it
        self.assertEqual(self.calls[0][1]["symbol"], "SPX")
        self.assertEqual(M.history("^GSPC", 1)["price"], 355.63)  # no quote: the last close stands in
        self.calls.clear()
        M.history("BTC-USD", 1)
        self.assertEqual(self.calls[0][1]["symbol"], "BTC/USD")

    def test_a_source_that_fails_hands_over_to_the_next(self):
        os.environ[M.TD_KEY] = "td-test-key-0000000001"
        os.environ[M.FH_KEY] = "fh-test-key-0000000001"
        self.answers = {"/time_series": M.Unavailable("HTTP 429"), "finnhub.io": FH_QUOTE, "finance/chart": YAHOO}
        h = M.history("AAPL", 1)  # just a quote: Finnhub before Yahoo
        self.assertEqual((h["source"], h["price"], h["closes"][0]), ("Finnhub", 356.1, ("prev", 348.51)))
        self.assertEqual(self.calls[-1][2], {"X-Finnhub-Token": "fh-test-key-0000000001"})
        h = M.history("AAPL", 5)  # history: Finnhub's free key has none, so Yahoo before Finnhub
        self.assertEqual(h["source"], "Yahoo Finance")
        self.answers = {"finnhub.io": {"c": 0, "pc": 0, "t": 0}}  # Finnhub's way of saying "unknown symbol"
        self.assertIsNone(M.history("ZZZZ", 1))
        self.calls.clear()
        self.assertIsNone(M.history("^GSPC", 1))  # an index: not sent to Finnhub at all
        self.assertFalse(any("finnhub" in u for u, _, _ in self.calls))

    def test_a_company_name_becomes_its_home_listing(self):
        os.environ[M.TD_KEY] = "td-test-key-0000000001"
        self.answers = {"/symbol_search": TD_SEARCH}
        self.assertEqual(M.resolve("nvidia"), "NVDA")  # not the Milan listing or the warrant that come first
        os.environ.pop(M.TD_KEY)
        os.environ[M.FH_KEY] = "fh-test-key-0000000001"
        self.answers = {"finnhub.io/api/v1/search": {"count": 2, "result": [
            {"description": "APPLE INC", "displaySymbol": "AAPL.MX", "symbol": "AAPL.MX", "type": "Common Stock"},
            {"description": "APPLE INC", "displaySymbol": "AAPL", "symbol": "AAPL", "type": "Common Stock"}]}}
        self.assertEqual(M.resolve("apple"), "AAPL")
        os.environ.pop(M.FH_KEY)
        self.answers = {"finance/search": {"quotes": [{"symbol": "TSLA", "quoteType": "EQUITY"}]}}
        self.assertEqual(M.resolve("tesla"), "TSLA")

    def test_the_answer_names_the_real_source(self):
        os.environ[M.TD_KEY] = "td-test-key-0000000001"
        self.answers = {"/time_series": TD_SERIES, "/quote": TD_QUOTE, "/symbol_search": TD_SEARCH}
        text = intents._stock("How did AAPL stock do over the last 3 days?", False, K)
        self.assertIn("Apple Inc. (AAPL) - last 3 trading days", text)
        self.assertIn("Twelve Data data - information, not investment advice.", text)
        self.assertNotIn("Yahoo", text)
        self.assertIn("Данни от Twelve Data", intents._stock("Как се движи акцията AAPL последните 3 дни?", True, K))
        from vaelon.config import Config
        from vaelon.tools import registry

        out = registry.execute(registry.Ctx(Config()), "stock_quote", {"symbol": "AAPL", "days": "3"})
        self.assertIn('source="twelve-data"', out)
        self.assertNotIn("td-test-key", out)

    def test_the_keys_are_known_and_bound_to_their_hosts(self):
        self.assertEqual((providers.KEY_HOSTS[M.TD_KEY], providers.KEY_HOSTS[M.FH_KEY]), ("api.twelvedata.com", "finnhub.io"))
        self.assertIn(M.TD_KEY, providers.EXTRA_KEYS)
        self.assertIn(M.FH_KEY, providers.EXTRA_KEYS)
        self.assertTrue(M.TD.startswith("https://" + providers.KEY_HOSTS[M.TD_KEY]))
        self.assertTrue(M.FH.startswith("https://" + providers.KEY_HOSTS[M.FH_KEY]))

    def test_an_error_body_is_never_passed_on(self):
        M._call = self.real

        class R:
            status_code = 401

            @staticmethod
            def json():
                return {"code": 401, "message": "apikey SECRET-ECHOED is incorrect", "status": "error"}

        import requests

        real_get, requests.get = requests.get, lambda *a, **k: R()
        try:
            with self.assertRaises(M.Unavailable) as e:
                M._call(M.TD + "/quote", {"symbol": "AAPL"}, {"Authorization": "apikey x"})
            self.assertNotIn("SECRET", str(e.exception))
        finally:
            requests.get = real_get


if __name__ == "__main__":
    unittest.main()
