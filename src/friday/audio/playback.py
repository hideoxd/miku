"""Chunked audio playback via sounddevice.

A background thread drains a queue of PCM buffers and plays them back-to-back,
so synthesis of the next sentence overlaps playback of the current one. Playback
is interruptible (``stop``) — the seam Phase 3 barge-in plugs into.
"""

from __future__ import annotations

import logging
import queue
import threading
import wave

import numpy as np

log = logging.getLogger("friday.audio")

try:
    import sounddevice as sd
except (ImportError, OSError) as exc:  # OSError: PortAudio lib missing
    sd = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _resolve_device(device: str):
    if not device:
        return None
    return int(device) if device.isdigit() else device


class AudioPlayer:
    """Thread-safe, interruptible chunked player."""

    def __init__(self, device: str = "") -> None:
        if sd is None:
            raise RuntimeError(
                f"sounddevice unavailable ({_IMPORT_ERROR}). Install the voice extra: "
                "pip install sounddevice"
            )
        self._device = _resolve_device(device)
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._done = threading.Event()
        self._done.set()  # idle to begin with
        self._thread = threading.Thread(target=self._run, name="audio-player", daemon=True)
        self._thread.start()

    def enqueue(self, pcm: np.ndarray, sample_rate: int) -> None:
        """Queue a mono float32 buffer for playback."""
        if pcm is None or len(pcm) == 0:
            return
        self._stop.clear()
        self._done.clear()
        self._q.put((np.ascontiguousarray(pcm, dtype=np.float32), sample_rate))

    def stop(self) -> None:
        """Interrupt playback now and drop anything queued (barge-in)."""
        self._stop.set()
        try:
            sd.stop()
        except Exception:  # noqa: BLE001
            pass
        _drain(self._q)
        self._done.set()

    def wait_done(self, timeout: float | None = None) -> bool:
        """Block until the queue is empty and playback has finished."""
        return self._done.wait(timeout)

    @property
    def is_playing(self) -> bool:
        return not self._done.is_set()

    def _run(self) -> None:
        while True:
            pcm, sr = self._q.get()  # blocks
            if self._stop.is_set():
                self._settle()
                continue
            try:
                sd.play(pcm, sr, device=self._device)
                self._wait_playback()
            except Exception:  # noqa: BLE001
                log.exception("playback failed")
            self._settle()

    def _wait_playback(self) -> None:
        """Wait for the current buffer, but poll so stop() can interrupt."""
        while True:
            stream = sd.get_stream()
            if stream is None or not stream.active:
                return
            if self._stop.is_set():
                sd.stop()
                return
            sd.sleep(20)

    def _settle(self) -> None:
        if self._q.empty():
            self._done.set()


def _drain(q: queue.Queue) -> None:
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass


def write_wav(path: str, pcm: np.ndarray, sample_rate: int) -> None:
    """Write a mono float32 buffer to a 16-bit WAV (stdlib only)."""
    clipped = np.clip(pcm, -1.0, 1.0)
    i16 = (clipped * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(i16.tobytes())


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """Read a WAV into a mono float32 buffer + its sample rate."""
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        channels = w.getnchannels()
        raw = w.readframes(w.getnframes())
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, sr
