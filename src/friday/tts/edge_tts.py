"""Microsoft Edge neural TTS — natural voice, free, needs internet.

This is also the *base voice* fed into the Phase-2 Miku RVC pipeline (the proven
mikuTTS recipe is edge-tts -> RVC), so getting it working now pays off twice.

Requires:  pip install edge-tts miniaudio
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np

log = logging.getLogger("friday.tts.edge")

# Sensible defaults; ja-JP tends to give a more Miku-like RVC input.
_DEFAULT_EN = "en-US-AriaNeural"
_DEFAULT_JA = "ja-JP-NanamiNeural"


class EdgeEngine:
    def __init__(self, voice: str = "", speed: float = 1.0, lang: str = "en") -> None:
        import edge_tts  # noqa: F401  (availability check)
        import miniaudio  # noqa: F401

        self.sample_rate = 24_000
        self.voice = voice.strip() or (_DEFAULT_JA if lang.startswith("ja") else _DEFAULT_EN)
        pct = int(round((speed - 1.0) * 100))
        self.rate = f"{pct:+d}%"

    def synthesize(self, text: str) -> np.ndarray:
        mp3 = asyncio.run(self._fetch(text))
        if not mp3:
            return np.zeros(0, dtype=np.float32)
        import miniaudio

        decoded = miniaudio.decode(
            mp3,
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=1,
            sample_rate=self.sample_rate,
        )
        return np.frombuffer(bytes(decoded.samples.tobytes()), dtype=np.float32).copy()

    async def _fetch(self, text: str) -> bytes:
        import edge_tts

        buf = bytearray()
        comm = edge_tts.Communicate(text, self.voice, rate=self.rate)
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)
