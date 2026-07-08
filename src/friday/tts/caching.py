"""A caching wrapper around any TTSEngine.

The Miku voice conversion (Phase 2) is slow, so repeated fixed lines ("Yes?",
greetings, confirmations, timer alerts) should be rendered once and replayed
from disk. This wrapper is engine-agnostic: it keys the cache on the wrapped
engine's identity + the text, storing a WAV per phrase and an in-memory copy for
the current session.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np

from ..audio.playback import read_wav, write_wav
from .base import TTSEngine

log = logging.getLogger("friday.tts.cache")


class CachingTTS:
    def __init__(self, inner: TTSEngine, cache_dir: str | Path, tag: str = "") -> None:
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Identity component so different engines/voices don't collide.
        self._tag = tag or type(inner).__name__
        self._sr = int(getattr(inner, "sample_rate", 22_050))
        self._mem: dict[str, np.ndarray] = {}

    @property
    def sample_rate(self) -> int:
        return self._sr

    @property
    def prefers_full_text(self) -> bool:
        return getattr(self.inner, "prefers_full_text", False)

    def _key(self, text: str) -> str:
        h = hashlib.sha1(f"{self._tag}|{text}".encode("utf-8")).hexdigest()[:16]
        return h

    def synthesize(self, text: str) -> np.ndarray:
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)

        if text in self._mem:
            return self._mem[text]

        wav = self.cache_dir / f"{self._key(text)}.wav"
        if wav.exists():
            pcm, sr = read_wav(str(wav))
            self._sr = sr
            self._mem[text] = pcm
            log.debug("cache hit: %r", text[:40])
            return pcm

        pcm = self.inner.synthesize(text)
        self._sr = int(self.inner.sample_rate)
        try:
            write_wav(str(wav), pcm, self._sr)
        except OSError:
            log.warning("could not write cache file %s", wav)
        self._mem[text] = pcm
        return pcm

    def prewarm(self, phrases: list[str]) -> int:
        """Render a batch of fixed lines ahead of time; returns count rendered."""
        n = 0
        for p in phrases:
            self.synthesize(p)
            n += 1
        return n
