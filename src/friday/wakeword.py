"""Wake-word detection with openWakeWord (free, CPU, ONNX).

Default model is the pretrained ``hey_jarvis`` — on-theme for a Stark-style AI
and works with zero setup. To use a literal "Hey Friday", train a custom model
with openWakeWord's Colab notebook and point FRIDAY_WAKE_MODEL at the .onnx file.

Feed 16 kHz int16 frames; ``score(frame)`` returns the current wake confidence.
"""

from __future__ import annotations

import logging
import os

import numpy as np

log = logging.getLogger("friday.wakeword")


class WakeWord:
    def __init__(self, model: str = "hey_jarvis", threshold: float = 0.5) -> None:
        import openwakeword
        from openwakeword.model import Model

        # Ensure the shared feature models (+ pretrained ww models) are present.
        try:
            openwakeword.utils.download_models()
        except Exception as exc:  # noqa: BLE001
            log.debug("download_models: %s", exc)

        self.threshold = threshold
        is_path = model.endswith(".onnx") or os.sep in model or "/" in model
        self._model = Model(wakeword_models=[model], inference_framework="onnx")
        # Remember the key openWakeWord will report scores under.
        self._name = os.path.splitext(os.path.basename(model))[0] if is_path else model

    def score(self, frame_int16: np.ndarray) -> float:
        """Highest wake score for this frame (openWakeWord buffers internally)."""
        scores = self._model.predict(frame_int16)
        if not scores:
            return 0.0
        # Prefer our model's key; fall back to the max across returned models.
        for key, val in scores.items():
            if self._name in key:
                return float(val)
        return float(max(scores.values()))

    def triggered(self, frame_int16: np.ndarray) -> bool:
        return self.score(frame_int16) >= self.threshold

    def reset(self) -> None:
        try:
            self._model.reset()
        except Exception:  # noqa: BLE001
            pass
