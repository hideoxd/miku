"""Windows SAPI5 voice — offline, zero-download, always available.

This is FRIDAY's Phase-1 placeholder voice: robotic but guaranteed to work on
any Windows box with no model downloads. It proves the whole audio-out path
(synthesize -> PCM -> playback) that Phases 2-3 reuse.
"""

from __future__ import annotations

import logging
import os
import tempfile
import wave

import numpy as np

log = logging.getLogger("friday.tts.sapi")

# SpeechStreamFileMode.SSFMCreateForWrite — using the literal avoids generating
# the comtypes SpeechLib typelib wrapper (which is flaky on some machines).
_SSFM_CREATE_FOR_WRITE = 3


class SapiEngine:
    def __init__(self, voice: str = "", speed: float = 1.0) -> None:
        # Verify COM + SAPI are usable up front so the factory can fall back.
        import comtypes.client  # noqa: F401  (import checks availability)

        self.sample_rate = 22_050  # updated from the actual WAV on each synth
        self._voice_hint = voice.strip()
        # SAPI rate is an int in [-10, 10]; map speed 1.0 -> 0, 2.0 -> +10.
        self._rate = int(max(-10, min(10, round((speed - 1.0) * 10))))

    def synthesize(self, text: str) -> np.ndarray:
        import comtypes
        import comtypes.client

        # SAPI is COM; ensure this thread has an apartment (idempotent).
        try:
            comtypes.CoInitialize()
        except OSError:
            pass

        sp = comtypes.client.CreateObject("SAPI.SpVoice")
        if self._voice_hint:
            self._select_voice(sp, self._voice_hint)
        sp.Rate = self._rate

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            stream.Open(tmp.name, _SSFM_CREATE_FOR_WRITE)
            sp.AudioOutputStream = stream
            sp.Speak(text)
            stream.Close()
            return self._load_wav(tmp.name)
        finally:
            try:
                os.remove(tmp.name)
            except OSError:
                pass

    def _select_voice(self, sp, hint: str) -> None:
        hint = hint.lower()
        for token in sp.GetVoices():
            try:
                desc = token.GetDescription()
            except Exception:  # noqa: BLE001
                continue
            if hint in desc.lower():
                sp.Voice = token
                log.debug("SAPI voice: %s", desc)
                return
        log.warning("SAPI voice matching %r not found; using default", hint)

    def _load_wav(self, path: str) -> np.ndarray:
        with wave.open(path, "rb") as w:
            self.sample_rate = w.getframerate()
            channels = w.getnchannels()
            raw = w.readframes(w.getnframes())
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        return data
