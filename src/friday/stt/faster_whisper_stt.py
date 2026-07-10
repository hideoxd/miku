"""Speech-to-text with faster-whisper (CTranslate2) on CPU.

base.en + int8 is the sweet spot on the i5-1235U: ~1 GB RAM, good enough for
commands, and fast. The model downloads once on first use.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("friday.stt")


class FasterWhisperSTT:
    def __init__(
        self,
        model: str = "base.en",
        compute_type: str = "int8",
        cpu_threads: int = 4,
        device: str = "cpu",
    ) -> None:
        from faster_whisper import WhisperModel

        log.info("loading faster-whisper model '%s' (%s, %s)…", model, device, compute_type)
        self._model = WhisperModel(
            model, device=device, compute_type=compute_type, cpu_threads=cpu_threads or 0
        )
        self.sample_rate = 16_000

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16_000) -> str:
        return self.transcribe_scored(audio, sample_rate)[0]

    def transcribe_scored(
        self, audio: np.ndarray, sample_rate: int = 16_000
    ) -> tuple[str, float, float, float]:
        """Transcribe and also return decode-confidence signals.

        Returns ``(text, avg_logprob, no_speech_prob, compression_ratio)``.
        Callers (the wake spotter) use these to reject Whisper's hallucinations
        on non-speech audio — base.en happily invents fluent sentences from fan
        noise or silence, which must not be treated as a spoken command.
        """
        if audio is None or len(audio) == 0:
            return "", -10.0, 1.0, 0.0
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if sample_rate != self.sample_rate:
            audio = _resample(audio, sample_rate, self.sample_rate)
        segments, _ = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,          # greedy — fastest, fine for commands
            vad_filter=False,     # we do our own VAD/endpointing
            condition_on_previous_text=False,
        )
        segs = list(segments)
        text = " ".join(seg.text.strip() for seg in segs).strip()
        if not segs:
            return "", -10.0, 1.0, 0.0
        avg_logprob = sum(s.avg_logprob for s in segs) / len(segs)
        no_speech = sum(s.no_speech_prob for s in segs) / len(segs)
        compression = max(s.compression_ratio for s in segs)
        return text, avg_logprob, no_speech, compression


def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return audio
    from scipy.signal import resample_poly
    from math import gcd

    g = gcd(src, dst)
    return resample_poly(audio, dst // g, src // g).astype(np.float32)
