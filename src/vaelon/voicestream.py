"""Streamed voice: the cloud voice (ElevenLabs) is played while it is still arriving.

Until v0.8 every sentence was fetched whole, then shaped by the Voice Designer, then played - so a long first
sentence was heard only after ElevenLabs had finished all of it. Now:

  ElevenLabs /stream  ->  DesignStream (the same effects, block by block)  ->  the app, chunk by chunk

`DesignStream` is the Voice Designer rebuilt for blocks of any size: every effect keeps the state it needs between
blocks (resampling position, filter and delay histories, oscillator phase), so the result does not depend on how
the audio was cut into pieces. Two things differ from the whole-clip version, on purpose and inaudibly small:
the smoothing filters look back instead of half ahead (~1.7 ms later), and instead of scaling the finished clip to
its loudest point - impossible before the clip exists - a limiter turns the level down when needed, never up.

Only the cloud voice is streamed. The local voice (Piper) makes a whole sentence in ~0.25 s; there it stays as it was.
Credits: a sentence already spoken comes from the cache without a new request; if ElevenLabs fails before sending
audio (not billed), the local voice answers - without a second cloud attempt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

from . import config, tts

RATE = 22050         # what is asked from ElevenLabs (raw 16-bit mono PCM)
CHUNK = 2048         # bytes read from the network at a time (~46 ms of audio)
CEILING = 0.95       # the limiter's ceiling (the whole-clip path scales its peak to 0.9)
GAIN0 = 1.4          # starting level: the whole-clip path lifts quiet clips up to 0.9 - so does this, then the
                     # limiter turns it down at the first loud block (a block is scaled as a whole: no clipping)


# ---------------------------------------------------------------- building blocks with memory

class _Taps:
    """y[n] = x[n] + sum(g * x[n - d]): comb delays, early reflections, echoes."""

    def __init__(self, taps):
        self.taps = [(int(d), float(g)) for d, g in taps if int(d) > 0 and g]
        self.n = max((d for d, _ in self.taps), default=0)
        self.h = np.zeros(self.n, np.float32)

    def __call__(self, x):
        if not self.n:
            return x
        ext = np.concatenate([self.h, x])
        y = x.copy()
        for d, g in self.taps:
            y += g * ext[self.n - d:self.n - d + len(x)]
        self.h = ext[len(ext) - self.n:]
        return y


class _Mean:
    """Moving average over the last k samples (causal)."""

    def __init__(self, k: int):
        self.k = max(1, int(k))
        self.h = np.zeros(self.k - 1, np.float32)

    def __call__(self, x):
        if self.k == 1:
            return x
        ext = np.concatenate([self.h, x])
        c = np.concatenate([[0.0], np.cumsum(ext, dtype=np.float64)])
        y = ((c[self.k:] - c[:-self.k]) / self.k).astype(np.float32)
        self.h = ext[len(ext) - (self.k - 1):]
        return y


class _Lag:
    """y[n] = x[n - d]: keeps two paths in step after one of them went through a filter."""

    def __init__(self, d: int):
        self.d = max(0, int(d))
        self.h = np.zeros(self.d, np.float32)

    def __call__(self, x):
        if not self.d:
            return x
        ext = np.concatenate([self.h, x])
        self.h = ext[len(ext) - self.d:]
        return ext[:len(x)]


class _Resample:
    """Pitch by resampling, exactly like the whole-clip version: outputs at input positions 0, p, 2p, ..."""

    def __init__(self, p: float):
        self.p = float(p)
        self.buf = np.zeros(0, np.float32)
        self.base = 0      # global index of buf[0]
        self.t = 0.0       # global position of the next output sample

    def __call__(self, x):
        self.buf = np.concatenate([self.buf, x])
        last = self.base + len(self.buf) - 1           # the whole-clip rule: positions strictly below len-1
        if self.t >= last:
            return np.zeros(0, np.float32)
        count = int(np.ceil((last - self.t) / self.p))
        pos = self.t + self.p * np.arange(count, dtype=np.float64)
        pos = pos[pos < last]
        local = pos - self.base
        i = np.floor(local).astype(np.int64)
        f = (local - i).astype(np.float32)
        y = self.buf[i] * (1 - f) + self.buf[i + 1] * f
        self.t = float(pos[-1] + self.p) if len(pos) else self.t
        keep = int(np.floor(self.t)) - self.base        # samples before this are never needed again
        if keep > 0:
            self.buf = self.buf[keep:]
            self.base += keep
        return y.astype(np.float32)


# ---------------------------------------------------------------- the Voice Designer, block by block

class DesignStream:
    """`feed(block)` -> shaped audio so far; `end()` -> the tail (reflections, echoes). float32 in and out."""

    def __init__(self, rate: int, v: dict, limit: bool = True):
        self.rate, self.v, self.limit, self.gain = rate, tts.normalize(v), limit, GAIN0
        v = self.v
        self.clean = all(v[k] == 0 for k in ("metal", "robot", "radio", "echo", "space")) and abs(v["pitch"] - 1) <= 0.01
        self.pitch = _Resample(v["pitch"]) if abs(v["pitch"] - 1.0) > 0.01 else None
        a = v["metal"]
        if a > 0:
            self.comb = _Taps([(rate * 8.5 / 1000, 0.35 * a), (rate * 13.2 / 1000, 0.25 * a)])
            self.sub_mean = _Mean(int(rate / 300))
            self.sub_n, self.sub_prev = 0, 0.0
        self.robot_n = 0
        r = v["radio"]
        if r > 0:
            k_hi, k_lo = max(1, int(rate / 3400)), max(2, int(rate / 300))
            self.hi, self.lo = _Mean(k_hi), _Mean(k_lo)
            self.band_lag = _Lag((k_lo - 1) // 2)
            self.dry_lag = _Lag((k_hi - 1) // 2 + (k_lo - 1) // 2)
        sp = v["space"]
        self.space = _Taps([(rate * ms / 1000, g * sp * 0.6) for ms, g in ((23, 0.5), (37, 0.4), (53, 0.32), (71, 0.25))]) if sp > 0 else None
        e = v["echo"]
        d = int(rate * 0.21)
        self.echo = _Taps([(d * k, (0.45 * e) ** k) for k in (1, 2, 3)]) if e > 0 else None
        self.space_tail, self.echo_tail = int(rate * 0.08), d * 3

    def _metal(self, x):
        a = self.v["metal"]
        out = self.comb(x)
        idx = self.sub_n + np.arange(len(x))           # crude octave-down: every sample takes the even one before it
        src = np.concatenate([[self.sub_prev], x])
        sub = np.where(idx % 2 == 0, src[1:], src[:-1]).astype(np.float32)
        if len(x):
            self.sub_prev = float(x[-1])
        self.sub_n += len(x)
        out = out + 0.35 * a * self.sub_mean(sub)
        return np.tanh(out * (1.0 + 0.8 * a)).astype(np.float32)

    def _robot(self, x):
        r = self.v["robot"]
        t = (self.robot_n + np.arange(len(x), dtype=np.float64)) / self.rate
        self.robot_n += len(x)
        return (x * (1 - r) + x * np.sin(2 * np.pi * 55 * t).astype(np.float32) * r * 1.6).astype(np.float32)

    def _radio(self, x):
        r = self.v["radio"]
        lp = self.hi(x)
        band = self.band_lag(lp) - self.lo(lp)
        return (self.dry_lag(x) * (1 - r) + np.tanh(band * 3.0) * r).astype(np.float32)

    def _out(self, y):
        if self.limit and len(y):
            peak = float(np.max(np.abs(y))) * self.gain
            if peak > CEILING:
                self.gain *= CEILING / peak               # turn down at once, never back up
            y = y * self.gain
        return y.astype(np.float32)

    def feed(self, x):
        x = np.asarray(x, np.float32)
        if self.clean:
            return x
        if self.pitch is not None:
            x = self.pitch(x)
        if self.v["metal"] > 0:
            x = self._metal(x)
        if self.v["robot"] > 0:
            x = self._robot(x)
        if self.v["radio"] > 0:
            x = self._radio(x)
        if self.space is not None:
            x = self.space(x)
        if self.echo is not None:
            x = self.echo(x)
        return self._out(x)

    def end(self):
        if self.clean:
            return np.zeros(0, np.float32)
        parts = []
        if self.space is not None:
            y = self.space(np.zeros(self.space_tail, np.float32))
            parts.append(self.echo(y) if self.echo is not None else y)
        if self.echo is not None:
            parts.append(self.echo(np.zeros(self.echo_tail, np.float32)))
        return self._out(np.concatenate(parts)) if parts else np.zeros(0, np.float32)


def to_pcm(x) -> bytes:
    """float -> 16-bit; the exact inverse of reading (/32768), so untouched audio comes out bit for bit."""
    return np.clip(np.round(np.asarray(x, np.float64) * 32768), -32768, 32767).astype("<i2").tobytes()


# ---------------------------------------------------------------- the voice for one sentence

@dataclass
class Voiced:
    """Either a finished clip (`wav`) or audio still arriving (`chunks`: 16-bit mono PCM at `rate`)."""
    wav: bytes = b""
    rate: int = RATE
    chunks: Iterator[bytes] | None = None
    engine: str = ""
    notes: list = field(default_factory=list)


def _cloud_request(text: str):
    """Open the ElevenLabs stream. Returns the open response, or raises (nothing was billed then)."""
    from . import speed
    from .security.dlp import scrub

    cfg = config.Config.load()
    vid = re.sub(r"[^A-Za-z0-9]", "", cfg.elevenlabs_voice or "JBFqnCBsd6RMkjVDRZzb")
    model = re.sub(r"[^a-z0-9_]", "", cfg.elevenlabs_model or "eleven_flash_v2_5")
    speed.used(tts.ELEVEN)
    r = speed.HTTP.post(f"{tts.ELEVEN}/v1/text-to-speech/{vid}/stream", params={"output_format": f"pcm_{RATE}"},
                        headers={"xi-api-key": config.env("ELEVENLABS_API_KEY")}, timeout=(10, 30),
                        allow_redirects=False,  # the key header must never follow a redirect to another host
                        stream=True, json={"text": scrub(text), "model_id": model})
    if r.status_code != 200:
        r.close()
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}")
    return r


def speak(text: str, voice: dict | None = None) -> Voiced:
    """The voice for one sentence, streamed when it comes from the cloud. Never raises for the cloud: if it is not
    available the local voice answers (and that one raises only if there is no voice at all)."""
    text = text.strip()[:1500]
    if not text:
        raise ValueError("empty text")
    v = tts.normalize(voice) if voice else tts.current_voice()
    key = tts.cache_key(text, v)
    hit = tts.cached(key)
    if hit is not None:  # said before: no request, no credits
        return Voiced(wav=hit, engine="cache")
    lang = tts.detect_lang(text)
    if tts._engine(lang) != "elevenlabs" or not tts.reserve(text):  # counted BEFORE the request (parallel sentences)
        return Voiced(wav=tts._synthesize(text, v, local_only=True) if tts._engine(lang) == "elevenlabs"
                      else tts.synthesize(text, voice=voice), engine="local")
    try:
        r = _cloud_request(text)
    except Exception as e:  # refused / unreachable before any audio: not billed - the local voice takes over
        tts._add_usage(-len(text))
        wav = tts.remember(key, tts._synthesize(text, v, local_only=True))
        return Voiced(wav=wav, engine="local", notes=[f"cloud voice unavailable ({type(e).__name__})"])

    def chunks():
        shaper, carry, done = DesignStream(RATE, v), b"", []
        try:
            for raw in r.iter_content(chunk_size=CHUNK):
                if not raw:
                    continue
                raw = carry + raw
                cut = len(raw) - len(raw) % 2         # a sample can be split between two network chunks
                carry = raw[cut:]
                x = np.frombuffer(raw[:cut], "<i2").astype(np.float32) / 32768.0
                y = shaper.feed(x)
                if len(y):
                    done.append(y)
                    yield to_pcm(y)
            tail = shaper.end()
            if len(tail):
                done.append(tail)
                yield to_pcm(tail)
            if done:  # complete: the same sentence next time comes from the cache
                tts.remember(key, tts._write_wav(np.concatenate(done), RATE))
        finally:
            r.close()

    return Voiced(chunks=chunks(), rate=RATE, engine="elevenlabs")
