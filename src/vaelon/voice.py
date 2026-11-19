"""Voice I/O, fully local: faster-whisper (STT, handles Bulgarian) + system TTS (pyttsx3).

Install:  pip install "vaelon[voice]"
Privacy: audio never leaves the machine; only the transcript after the wake word is processed.
Non-wake-word speech is discarded immediately and never stored.
"""
from __future__ import annotations

import time


class Voice:
    RATE = 16000

    def __init__(self, cfg):
        try:
            import numpy as np  # noqa: F401
            import sounddevice as sd  # noqa: F401
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError('voice extras missing: pip install "vaelon[voice]"') from e
        self.cfg = cfg
        self.stt = WhisperModel(cfg.whisper_model, compute_type="int8")
        try:
            import pyttsx3

            self.tts = pyttsx3.init()
        except Exception:
            self.tts = None

    def listen(self, max_seconds: int = 12, silence: float = 1.0) -> str:
        """Record until ~1s of silence (energy VAD), then transcribe locally."""
        import numpy as np
        import sounddevice as sd

        chunk, frames, quiet, started = int(self.RATE * 0.2), [], 0.0, False
        t0 = time.time()
        with sd.InputStream(samplerate=self.RATE, channels=1, dtype="float32") as s:
            while time.time() - t0 < max_seconds:
                data, _ = s.read(chunk)
                loud = float(np.abs(data).mean()) > 0.01
                if loud:
                    started, quiet = True, 0.0
                elif started:
                    quiet += 0.2
                if started:
                    frames.append(data[:, 0])
                if started and quiet >= silence:
                    break
        if not frames:
            return ""
        audio = np.concatenate(frames)
        segs, _ = self.stt.transcribe(audio, vad_filter=True)
        return " ".join(x.text.strip() for x in segs).strip()

    def speak(self, text: str) -> None:
        if self.tts:
            self.tts.say(text)
            self.tts.runAndWait()

    def strip_wake(self, text: str) -> str | None:
        """Return the command after the wake word, or None if the wake word was not said."""
        low, w = text.lower(), self.cfg.wake_word.lower()
        for variant in (w, "вейлон", "ваелон", "вейлън"):
            i = low.find(variant)
            if i != -1:
                return text[i + len(variant):].strip(" ,.!?:;")
        return None

    def loop(self, agent) -> None:
        print(f"Listening for '{self.cfg.wake_word}'... (Ctrl+C to stop)")
        while True:
            heard = self.listen()
            cmd = self.strip_wake(heard) if heard else None
            if cmd is None:
                continue  # discarded - not addressed to Vaelon
            if not cmd:
                self.speak("Yes?")
                cmd = self.listen()
            if cmd:
                print(f"> {cmd}")
                answer = agent.run(cmd)
                print(answer)
                self.speak(answer)
