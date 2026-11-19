"""Streamed cloud voice: the Voice Designer block by block, the ElevenLabs stream, credits, the /tts stream answer.
Offline: ElevenLabs is replaced by a stand-in; NO request reaches the real service and no credit is spent."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from vaelon import config, server, speed, tts, voicestream as vs  # noqa: E402
from vaelon.config import Config  # noqa: E402

RATE = 22050
KEY = "sk_" + "streamtest" * 3  # made up for the test


def speechlike(seconds=1.5, level=0.8):
    rng = np.random.default_rng(7)
    t = np.arange(int(RATE * seconds)) / RATE
    x = (np.sin(2 * np.pi * 140 * t) * 0.4 + rng.normal(0, 0.08, len(t))) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)) ** 2
    return (x / np.max(np.abs(x)) * level).astype(np.float32)


def shaped(v, x, sizes, limit=False):
    s, out, i, k = vs.DesignStream(RATE, v, limit=limit), [], 0, 0
    while i < len(x):
        n = sizes[k % len(sizes)]
        out.append(s.feed(x[i:i + n]))
        i, k = i + n, k + 1
    out.append(s.end())
    return np.concatenate(out)


class Effects(unittest.TestCase):
    def test_the_result_does_not_depend_on_how_the_audio_was_cut(self):
        x = speechlike()
        for name in tts.PRESETS:
            v = tts.normalize({"preset": name})
            a, b = shaped(v, x, [512]), shaped(v, x, [37, 4000, 1, 999, 2048])
            self.assertEqual(len(a), len(b), name)
            self.assertLess(float(np.max(np.abs(a - b))), 1e-6, name)

    def test_it_sounds_like_the_whole_clip_version(self):
        x = speechlike()
        env = lambda y, n: np.convolve(np.abs(y[:n]), np.ones(220) / 220, "same")  # noqa: E731
        for name in tts.PRESETS:
            v = tts.normalize({"preset": name})
            a, whole = shaped(v, x, [1024]), tts.design(x, RATE, v)
            self.assertLessEqual(abs(len(a) - len(whole)), 2, name)  # same pitch change, same echo tails
            n = min(len(a), len(whole))
            corr = np.corrcoef(env(a / np.max(np.abs(a)), n), env(whole, n))[0, 1]
            self.assertGreater(corr, 0.99, name)

    def test_clean_is_untouched_and_the_limiter_never_clips(self):
        x = speechlike(level=0.6)
        self.assertTrue(np.array_equal(shaped(tts.normalize({"preset": "clean"}), x, [700], limit=True), x))
        for level in (0.3, 1.0):
            for name in ("vaelon", "titan", "radio", "ghost"):
                y = shaped(tts.normalize({"preset": name}), speechlike(level=level), [1024], limit=True)
                self.assertLessEqual(float(np.max(np.abs(y))), vs.CEILING + 1e-6, name)
        loud = shaped(tts.normalize({"preset": "vaelon"}), speechlike(level=0.8), [1024], limit=True)
        self.assertGreater(float(np.max(np.abs(loud))), 0.85)  # as loud as the whole-clip voice (0.9), not quieter


class FakeCloud:
    """Stands in for ElevenLabs: answers the stream request with 16-bit PCM in uneven pieces (odd sizes too)."""

    def __init__(self, status=200, pcm=b""):
        self.status, self.pcm, self.calls = status, pcm, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        fake = self

        class R:
            status_code = fake.status
            closed = False

            def iter_content(self, chunk_size=1):
                data, i, sizes = fake.pcm, 0, [1, 4095, 3, 2048, 777]
                k = 0
                while i < len(data):
                    n = sizes[k % len(sizes)]
                    yield data[i:i + n]
                    i, k = i + n, k + 1

            def close(self):
                self.closed = True

        return R()


class Cloud(unittest.TestCase):
    def setUp(self):
        self.real_post, self.real_piper, self.real_ready = speed.HTTP.post, tts._piper, tts._piper_ready
        self.local = []
        tts._piper_ready = lambda lang: True  # the local voice is "installed" (a stand-in, no model is loaded)
        tts._piper = lambda text, lang, *a, **k: self.local.append(text) or tts._write_wav(speechlike(0.5), RATE)
        tts._wav_cache.clear()
        os.environ["ELEVENLABS_API_KEY"] = KEY
        cfg = Config(tts_engine="elevenlabs", elevenlabs_monthly_chars=8000, voice={"preset": "vaelon"})
        cfg.save()
        (config.HOME / "usage.json").unlink(missing_ok=True)
        self.pcm = (speechlike(1.0) * 32767).astype("<i2").tobytes()

    def tearDown(self):
        speed.HTTP.post, tts._piper, tts._piper_ready = self.real_post, self.real_piper, self.real_ready
        os.environ.pop("ELEVENLABS_API_KEY", None)
        tts._wav_cache.clear()

    def use(self, cloud):
        speed.HTTP.post = cloud.post
        return cloud

    def test_the_cloud_voice_streams_and_is_billed_once(self):
        cloud = self.use(FakeCloud(pcm=self.pcm))
        text = "Streaming is faster, my key is " + KEY  # a stored secret must never reach the voice service
        got = vs.speak(text)
        self.assertEqual((got.engine, got.rate), ("elevenlabs", 22050))
        self.assertIsNotNone(got.chunks)
        url, kw = cloud.calls[0]
        self.assertTrue(url.endswith("/stream"))
        self.assertTrue(url.startswith("https://api.elevenlabs.io/v1/text-to-speech/"))
        self.assertEqual(kw["params"], {"output_format": "pcm_22050"})
        self.assertEqual(kw["headers"], {"xi-api-key": KEY})
        self.assertTrue(kw["stream"])
        self.assertFalse(kw["allow_redirects"])
        self.assertNotIn(KEY, kw["json"]["text"])
        self.assertEqual(kw["json"]["model_id"], "eleven_flash_v2_5")
        audio = b"".join(got.chunks)
        self.assertEqual(len(audio) % 2, 0)  # pieces split in the middle of a sample were joined again
        whole = tts.design(np.frombuffer(self.pcm, "<i2").astype(np.float32) / 32768, RATE, tts.normalize({"preset": "vaelon"}))
        self.assertLessEqual(abs(len(audio) // 2 - len(whole)), 2)  # shaped like the voice designer says, tails included
        self.assertEqual(tts.elevenlabs_used(), len(text))
        again = vs.speak(text)  # the same sentence once more: from the cache - no request, no credits
        self.assertEqual((again.engine, len(cloud.calls), tts.elevenlabs_used()), ("cache", 1, len(text)))
        with wave.open(io.BytesIO(again.wav)) as w:
            self.assertEqual((w.getframerate(), w.getnframes()), (22050, len(audio) // 2))

    def test_a_refusal_before_any_audio_falls_back_to_the_local_voice_without_a_second_try(self):
        cloud = self.use(FakeCloud(status=401))
        got = vs.speak("Hello there.")
        self.assertEqual((got.engine, len(cloud.calls)), ("local", 1))  # one cloud attempt, then the local voice
        self.assertTrue(got.wav.startswith(b"RIFF"))
        self.assertEqual(self.local, ["Hello there."])
        self.assertEqual(tts.elevenlabs_used(), 0)  # nothing was billed, nothing is counted

    def test_no_cloud_request_when_the_cap_is_reached_or_the_voice_is_local(self):
        cloud = self.use(FakeCloud(pcm=self.pcm))
        Config(tts_engine="elevenlabs", elevenlabs_monthly_chars=5).save()
        self.assertEqual(vs.speak("This sentence is longer than the cap.").engine, "local")
        Config(tts_engine="piper").save()
        self.assertEqual(vs.speak("A local sentence.").engine, "local")
        self.assertEqual(cloud.calls, [])

    def test_stopping_early_closes_the_cloud_connection_and_caches_nothing(self):
        opened = []
        cloud = self.use(FakeCloud(pcm=self.pcm))
        real = cloud.post
        cloud.post = lambda url, **kw: opened.append(real(url, **kw)) or opened[-1]
        speed.HTTP.post = cloud.post
        got = vs.speak("Interrupted sentence.")
        next(got.chunks)
        got.chunks.close()  # you spoke over it
        self.assertTrue(opened[0].closed)
        self.assertEqual(len(tts._wav_cache), 0)  # half a sentence is never replayed from the cache


class Api(unittest.TestCase):
    def setUp(self):
        self.real_post, self.real_piper, self.real_ready = speed.HTTP.post, tts._piper, tts._piper_ready
        tts._piper_ready = lambda lang: True
        tts._piper = lambda text, lang, *a, **k: tts._write_wav(speechlike(0.5), RATE)
        tts._wav_cache.clear()
        os.environ["ELEVENLABS_API_KEY"] = KEY
        Config(tts_engine="elevenlabs", voice={"preset": "clean"}).save()
        (config.HOME / "usage.json").unlink(missing_ok=True)
        self.pcm = (speechlike(1.0) * 32767).astype("<i2").tobytes()
        speed.HTTP.post = FakeCloud(pcm=self.pcm).post
        cfg = Config(provider="mock")
        self.token = server.get_token()
        self.srv = server.serve(cfg, port=0)
        tts.UI_UP.set()
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        speed.HTTP.post, tts._piper, tts._piper_ready = self.real_post, self.real_piper, self.real_ready
        os.environ.pop("ELEVENLABS_API_KEY", None)
        tts._wav_cache.clear()
        self.srv.shutdown()
        self.srv.server_close()

    def post(self, body, token=True):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/tts", data=json.dumps(body).encode(), method="POST",
                                     headers={"Origin": "http://localhost:3100"})
        if token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            r = urllib.request.urlopen(req, timeout=20)
            return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_the_app_gets_a_stream_only_when_it_asks_for_one(self):
        self.assertEqual(self.post({"text": "Hi.", "stream": True}, token=False)[0], 401)
        code, headers, body = self.post({"text": "Streamed through the core.", "stream": True})
        self.assertEqual((code, headers["Content-Type"], headers["X-Sample-Rate"]), (200, "audio/L16; rate=22050; channels=1", "22050"))
        self.assertEqual(headers["Access-Control-Expose-Headers"], "X-Sample-Rate")
        self.assertEqual(body, self.pcm)  # the clean preset: exactly what the voice service sent
        code, headers, body = self.post({"text": "Streamed through the core.", "stream": True})
        self.assertEqual((code, headers["Content-Type"]), (200, "audio/wav"))  # said before: a finished clip, no credits
        code, headers, body = self.post({"text": "A preview of the voice."})  # the Voice Designer's preview
        self.assertEqual(headers["Content-Type"], "audio/wav")
        self.assertTrue(body.startswith(b"RIFF"))


if __name__ == "__main__":
    unittest.main()
