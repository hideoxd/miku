"""Voice-activity detection with Silero VAD.

Used for two things:
  * endpointing — decide when the user has finished speaking (trailing silence)
  * barge-in    — detect that the user started talking while FRIDAY is speaking

Works on fixed 512-sample windows at 16 kHz (the model's native window).
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("friday.vad")

WINDOW = 512  # samples @ 16 kHz (~32 ms)


class SileroVad:
    def __init__(self, threshold: float = 0.5, sample_rate: int = 16_000) -> None:
        from silero_vad import load_silero_vad

        self.threshold = threshold
        self.sample_rate = sample_rate
        try:
            self._model = load_silero_vad(onnx=True)
        except Exception:  # noqa: BLE001 — fall back to the torch model
            self._model = load_silero_vad(onnx=False)

    def reset(self) -> None:
        try:
            self._model.reset_states()
        except Exception:  # noqa: BLE001
            pass

    def prob(self, frame: np.ndarray) -> float:
        """Speech probability for a 512-sample float32 window."""
        import torch

        frame = np.ascontiguousarray(frame[:WINDOW], dtype=np.float32)
        if len(frame) < WINDOW:
            frame = np.pad(frame, (0, WINDOW - len(frame)))
        with torch.no_grad():
            out = self._model(torch.from_numpy(frame), self.sample_rate)
        return float(out.item())

    def is_speech(self, frame: np.ndarray) -> bool:
        return self.prob(frame) >= self.threshold
