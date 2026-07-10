"""Microphone capture via sounddevice — a stream of 16 kHz mono float32 frames.

Yields fixed 512-sample frames (~32 ms), which is Silero-VAD's native window and
a convenient unit for wake-word scoring too.
"""

from __future__ import annotations

import logging
import queue

import numpy as np

log = logging.getLogger("friday.audio.capture")

try:
    import sounddevice as sd
except (ImportError, OSError) as exc:
    sd = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

FRAME = 512  # samples @ 16 kHz


def _resolve_device(device: str):
    if not device:
        return None
    return int(device) if device.isdigit() else device


class MicStream:
    def __init__(self, sample_rate: int = 16_000, device: str = "", frame: int = FRAME) -> None:
        if sd is None:
            raise RuntimeError(
                f"sounddevice unavailable ({_IMPORT_ERROR}). Install: pip install sounddevice"
            )
        self.sample_rate = sample_rate
        self.frame = frame
        self._device = _resolve_device(device)
        # Bounded to ~30 s of audio: nobody drains the queue while the LLM is
        # thinking, and an unbounded queue would grow for as long as a reply
        # (or a hang) lasts. On overflow the *oldest* frames are dropped.
        max_frames = int(30 * sample_rate / frame)
        self._q: queue.Queue = queue.Queue(maxsize=max_frames)
        self._stream: "sd.InputStream | None" = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            log.debug("mic status: %s", status)
        # indata is (frames, channels) float32; take channel 0.
        chunk = indata[:, 0].copy()
        try:
            self._q.put_nowait(chunk)
        except queue.Full:
            try:
                self._q.get_nowait()  # drop the oldest frame
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(chunk)
            except queue.Full:
                pass  # racing consumers refilled it; losing one frame is fine

    def __enter__(self) -> "MicStream":
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame,
            channels=1,
            dtype="float32",
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self, timeout: float | None = None) -> np.ndarray:
        """Next frame of `frame` float32 samples (blocks)."""
        return self._q.get(timeout=timeout)

    def drain(self) -> None:
        """Discard buffered frames (e.g. after playback, to drop echo)."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    @staticmethod
    def to_int16(frame: np.ndarray) -> np.ndarray:
        return (np.clip(frame, -1.0, 1.0) * 32767.0).astype(np.int16)
