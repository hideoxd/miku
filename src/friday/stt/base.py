"""Speech-to-text engine interface (implemented in Phase 3).

Kept here in Phase 0 so the pipeline is designed around a stable seam: any
engine (faster-whisper, whisper.cpp, cloud) that turns audio frames into text
can be dropped in without touching the state machine.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np  # type: ignore  # only needed once Phase 3 deps are installed


@runtime_checkable
class STTEngine(Protocol):
    def transcribe(self, audio: "np.ndarray", sample_rate: int = 16_000) -> str:
        """Transcribe a mono float32 PCM buffer to text."""
        ...
