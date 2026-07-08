"""Text-to-speech engine interface (implemented in Phase 1+).

A ``TTSEngine`` turns a sentence into PCM audio. The Miku voice conversion in
Phase 2 is itself a ``TTSEngine`` that wraps a base engine and re-timbres its
output — so callers never change.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np  # type: ignore  # needs the `voice` extra installed


@runtime_checkable
class TTSEngine(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> "np.ndarray":
        """Render text to a mono float32 PCM buffer at ``self.sample_rate``."""
        ...
