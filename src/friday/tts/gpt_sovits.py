"""Miku voice via GPT-SoVITS zero-shot cloning on a hosted Space.

Given a short reference clip of a voice (3-10s), GPT-SoVITS clones its timbre to
speak arbitrary text. Point ``ref_audio`` at a clean Hatsune Miku clip and this
becomes FRIDAY's Miku voice — running on a free hosted GPU, nothing heavy local.

The engine calls the Space's ``/get_tts_wav`` endpoint (see the 13-arg signature
of lj1995/GPT-SoVITS-ProPlus / -v2). It is a normal TTSEngine, so the Speaker,
caching layer, and playback path all work unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..audio.playback import read_wav
from ._spaces import client_auth_kwargs, extract_audio_path
from .base import TTSEngine  # noqa: F401  (documents the interface we implement)

log = logging.getLogger("friday.tts.miku")

# GPT-SoVITS uses Chinese UI labels for its language / cut options.
_LANG = {
    "zh": "中文", "en": "英文", "ja": "日文", "ko": "韩文", "yue": "粤语",
    "auto": "多语种混合",
}
_CUT = {
    "none": "不切",
    "4sent": "凑四句一切",
    "50char": "凑50字一切",
    "zh_period": "按中文句号。切",
    "en_period": "按英文句号.切",
    "punct": "按标点符号切",
}


class GptSovitsMikuEngine:
    # Remote GPU call per request — synthesize the whole reply at once.
    prefers_full_text = True

    def __init__(
        self,
        space_id: str,
        ref_audio: str,
        *,
        ref_text: str = "",
        ref_lang: str = "ja",
        text_lang: str = "en",
        cut: str = "punct",
        speed: float = 1.0,
        top_k: int = 15,
        top_p: float = 1.0,
        temperature: float = 1.0,
        hf_token: str | None = None,
    ) -> None:
        if not space_id:
            raise RuntimeError("FRIDAY_MIKU_SPACE_ID is not set (e.g. lj1995/GPT-SoVITS-ProPlus).")
        if not ref_audio or not Path(ref_audio).exists():
            raise RuntimeError(
                f"Miku reference clip not found: {ref_audio!r}. Set FRIDAY_MIKU_REF_AUDIO to a "
                "3-10s WAV of the target voice."
            )

        from gradio_client import Client

        # These Spaces run on ZeroGPU; the token must be visible to both the
        # gradio client and huggingface_hub to allocate the GPU.
        if hf_token:
            import os

            os.environ.setdefault("HF_TOKEN", hf_token)

        self._ref_audio = str(ref_audio)
        self._ref_text = ref_text.strip()
        self._ref_free = not self._ref_text  # no transcript -> ref-free mode
        self._prompt_language = _LANG.get(ref_lang, "日文")
        self._text_language = _LANG.get(text_lang, "英文")
        self._how_to_cut = _CUT.get(cut, "按标点符号切")
        self._speed = float(speed)
        self._top_k = float(top_k)
        self._top_p = float(top_p)
        self._temperature = float(temperature)
        self.sample_rate = 32_000  # GPT-SoVITS v2/ProPlus output; refined per call

        log.info("connecting to GPT-SoVITS Space: %s", space_id)
        self.client = Client(space_id, **client_auth_kwargs(Client, hf_token))

    def synthesize(self, text: str) -> np.ndarray:
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)

        from gradio_client import handle_file

        result = self.client.predict(
            handle_file(self._ref_audio),  # ref_wav_path
            self._ref_text,                # prompt_text
            self._prompt_language,         # prompt_language
            text,                          # text
            self._text_language,           # text_language
            self._how_to_cut,              # how_to_cut
            self._top_k,                   # top_k
            self._top_p,                   # top_p
            self._temperature,             # temperature
            self._ref_free,                # ref_free
            self._speed,                   # speed
            False,                         # if_freeze
            [],                            # inp_refs (extra references)
            api_name="/get_tts_wav",
        )

        wav_path = extract_audio_path(result)
        if not wav_path:
            log.warning("GPT-SoVITS returned no audio path: %r", result)
            return np.zeros(0, dtype=np.float32)
        pcm, sr = read_wav(wav_path)
        self.sample_rate = sr
        return pcm
