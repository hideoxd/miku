"""Piper — fast, fully-offline neural TTS (CPU real-time), high quality-per-watt.

Needs a downloaded voice model (.onnx + .onnx.json). Grab one from
https://huggingface.co/rhasspy/piper-voices (e.g. en_US-lessac-medium) and point
FRIDAY_TTS_VOICE at the .onnx file.

Requires:  pip install piper-tts
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("friday.tts.piper")


class PiperEngine:
    def __init__(self, model_path: str = "", speed: float = 1.0) -> None:
        if not model_path:
            raise RuntimeError(
                "Piper needs a voice model: set FRIDAY_TTS_VOICE to a .onnx path "
                "(download from huggingface.co/rhasspy/piper-voices)."
            )
        path = Path(model_path)
        if not path.exists():
            raise RuntimeError(f"Piper model not found: {path}")

        from piper import PiperVoice

        self._voice = PiperVoice.load(str(path))
        self.sample_rate = int(self._voice.config.sample_rate)
        # length_scale < 1 speaks faster; invert the intuitive `speed`.
        self._length_scale = 1.0 / speed if speed else 1.0

    def synthesize(self, text: str) -> np.ndarray:
        chunks: list[np.ndarray] = []
        for audio in self._voice.synthesize(text, length_scale=self._length_scale):
            # piper 1.x yields AudioChunk objects with int16 PCM bytes.
            chunks.append(np.frombuffer(audio.audio_int16_bytes, dtype=np.int16))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32) / 32768.0
