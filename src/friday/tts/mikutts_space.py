"""Miku voice via a hosted mikuTTS Space (edge-tts base -> RVC Miku).

This is FRIDAY's default Miku engine: text in, Hatsune Miku audio out, using the
built-in Miku RVC models on John6666/mikuTTS. No reference clip, nothing heavy
local. Runs on HF ZeroGPU, so an HF token is required.

The Space's /tts signature (positional):
    model_name, speed, volume, pitch, tts_text, tts_voice,
    f0_up_key, f0_method, index_rate, protect
Returns: (info_str, edge_voice_path, result_path). speed/volume/pitch MUST be
ints — the Space formats them into an edge-tts rate string and a float like 0.0
produces the invalid rate "+0.0%".
"""

from __future__ import annotations

import logging

import numpy as np

from ..audio.playback import read_wav
from ._spaces import client_auth_kwargs, extract_audio_path

log = logging.getLogger("friday.tts.miku")


class MikuTTSSpaceEngine:
    # Each call pays a large ZeroGPU allocation cost, so synthesize the whole
    # reply in one request rather than sentence-by-sentence.
    prefers_full_text = True

    def __init__(
        self,
        space_id: str = "John6666/mikuTTS",
        *,
        model: str = "HATSUNE MIKU",
        base_voice: str = "en-US-AriaNeural-Female",
        f0_up_key: int = 6,
        f0_method: str = "rmvpe",
        index_rate: float = 0.75,
        protect: float = 0.33,
        speed: int = 0,
        volume: int = 0,
        pitch: int = 0,
        hf_token: str | None = None,
    ) -> None:
        if not space_id:
            raise RuntimeError("FRIDAY_MIKU_SPACE_ID is not set (e.g. John6666/mikuTTS).")

        from gradio_client import Client

        if hf_token:
            import os

            os.environ.setdefault("HF_TOKEN", hf_token)

        self.model = model
        self.base_voice = base_voice
        self.f0_up_key = int(f0_up_key)
        self.f0_method = f0_method
        self.index_rate = float(index_rate)
        self.protect = float(protect)
        # Ints on purpose (see module docstring).
        self.speed = int(speed)
        self.volume = int(volume)
        self.pitch = int(pitch)
        self.sample_rate = 40_000  # refined from the returned wav

        log.info("connecting to mikuTTS Space: %s (model=%s)", space_id, model)
        self.client = Client(space_id, **client_auth_kwargs(Client, hf_token))

    def synthesize(self, text: str) -> np.ndarray:
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)

        result = self.client.predict(
            self.model,        # model_name
            self.speed,        # speed (int!)
            self.volume,       # volume (int!)
            self.pitch,        # pitch (int!)
            text,              # tts_text
            self.base_voice,   # tts_voice
            self.f0_up_key,    # f0_up_key
            self.f0_method,    # f0_method
            self.index_rate,   # index_rate
            self.protect,      # protect
            api_name="/tts",
        )

        # (info, edge_voice_path, result_path)
        info = result[0] if isinstance(result, (list, tuple)) else ""
        path = None
        if isinstance(result, (list, tuple)) and len(result) >= 3:
            path = result[2] if isinstance(result[2], str) else extract_audio_path(result)
        else:
            path = extract_audio_path(result)

        if not path:
            raise RuntimeError(f"mikuTTS returned no audio. Info: {str(info)[:300]}")
        pcm, sr = read_wav(path)
        self.sample_rate = sr
        return pcm
