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
import os
import tempfile
import wave
from collections import OrderedDict
from pathlib import Path

import numpy as np

from ..audio.playback import read_wav, write_wav
from .base import TTSEngine

log = logging.getLogger("friday.tts.cache")


class CachingTTS:
    # Bounds so a 24/7 daemon rendering ever-new LLM sentences doesn't grow the
    # in-memory dict / cache dir without limit.
    _MEM_MAX = 256
    _DISK_MAX = 512

    def __init__(self, inner: TTSEngine, cache_dir: str | Path, tag: str = "") -> None:
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Identity component so different engines/voices don't collide.
        self._tag = tag or type(inner).__name__
        self._sr = int(getattr(inner, "sample_rate", 22_050))
        # LRU: most-recently-used at the end, oldest evicted from the front.
        self._mem: "OrderedDict[str, np.ndarray]" = OrderedDict()

    @property
    def sample_rate(self) -> int:
        return self._sr

    @property
    def prefers_full_text(self) -> bool:
        return getattr(self.inner, "prefers_full_text", False)

    def _key(self, text: str) -> str:
        h = hashlib.sha1(f"{self._tag}|{text}".encode("utf-8")).hexdigest()[:16]
        return h

    def _remember(self, text: str, pcm: np.ndarray) -> None:
        # Insert as most-recently-used and evict the oldest over the cap.
        self._mem[text] = pcm
        self._mem.move_to_end(text)
        while len(self._mem) > self._MEM_MAX:
            self._mem.popitem(last=False)

    def _write_atomic(self, wav: Path, pcm: np.ndarray) -> None:
        # Write to a temp file in the same dir then atomically rename onto the
        # final path, so a crash/kill mid-write can never leave a truncated WAV
        # at the cache path (which would poison every later read of this phrase).
        fd, tmp = tempfile.mkstemp(dir=str(self.cache_dir), suffix=".wav.tmp")
        os.close(fd)
        try:
            write_wav(tmp, pcm, self._sr)
            os.replace(tmp, str(wav))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._prune_disk()

    def _prune_disk(self) -> None:
        # Evict oldest (by mtime) cached WAVs over the cap so dynamic one-shot
        # replies don't grow the cache dir forever.
        try:
            files = [p for p in self.cache_dir.glob("*.wav") if p.is_file()]
        except OSError:
            return
        if len(files) <= self._DISK_MAX:
            return
        stamped = []
        for p in files:
            try:
                stamped.append((p.stat().st_mtime, p))
            except OSError:
                continue
        stamped.sort(key=lambda t: t[0])
        for _, p in stamped[: max(0, len(stamped) - self._DISK_MAX)]:
            try:
                p.unlink()
            except OSError:
                pass

    def synthesize(self, text: str) -> np.ndarray:
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)

        cached = self._mem.get(text)
        if cached is not None:
            self._mem.move_to_end(text)
            return cached

        wav = self.cache_dir / f"{self._key(text)}.wav"
        if wav.exists():
            try:
                pcm, sr = read_wav(str(wav))
            except (wave.Error, EOFError, OSError):
                # Corrupt/truncated cache file (e.g. killed mid-write): drop it
                # and fall through to re-synthesize instead of failing forever.
                log.warning("corrupt cache file %s; re-rendering", wav)
                try:
                    wav.unlink()
                except OSError:
                    pass
            else:
                self._sr = sr
                self._remember(text, pcm)
                log.debug("cache hit: %r", text[:40])
                return pcm

        pcm = self.inner.synthesize(text)
        self._sr = int(self.inner.sample_rate)
        # Don't cache an empty result: for non-empty input that means a transient
        # engine/network failure, and caching silence would mute the phrase
        # forever. Return it and let the next call retry.
        if pcm is None or len(pcm) == 0:
            return pcm
        try:
            self._write_atomic(wav, pcm)
        except OSError:
            log.warning("could not write cache file %s", wav)
        self._remember(text, pcm)
        return pcm

    def prewarm(self, phrases: list[str]) -> int:
        """Render a batch of fixed lines ahead of time; returns count rendered."""
        n = 0
        for p in phrases:
            self.synthesize(p)
            n += 1
        return n
