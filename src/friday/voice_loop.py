"""Voice-loop building blocks: utterance capture, barge-in, push-to-talk.

The hands-free loop itself lives in :mod:`friday.service` (``VoiceService``),
which composes ``capture_utterance`` and ``_speak_with_bargein`` from here.
``run_ptt`` is the simple press-Enter-then-speak CLI mode.

Headphones are assumed so the mic doesn't hear Miku (which would false-trigger
barge-in and transcribe her own speech).
"""

from __future__ import annotations

import logging
import queue
import threading

import numpy as np

from .audio.capture import MicStream
from .config import Settings

log = logging.getLogger("friday.voice")

def _frame_ms(settings: Settings, mic: MicStream) -> float:
    return mic.frame / settings.mic_sample_rate * 1000.0


def capture_utterance(
    mic: MicStream, vad, settings: Settings, *, start_timeout_s: float = 8.0
) -> np.ndarray:
    """Record from the mic until the user stops talking (VAD endpointing).

    Returns the utterance audio (float32 @ mic sample rate), or an empty array
    if no speech began within ``start_timeout_s``.
    """
    vad.reset()
    frame_ms = _frame_ms(settings, mic)
    silence_limit = max(1, int(settings.vad_silence_ms / frame_ms))
    max_frames = int(settings.max_utterance_s * 1000 / frame_ms)
    start_limit = int(start_timeout_s * 1000 / frame_ms)

    preroll: list[np.ndarray] = []
    preroll_max = max(3, int(300 / frame_ms))  # ~300 ms before speech
    collected: list[np.ndarray] = []
    started = False
    silence = 0
    waited = 0

    while len(collected) < max_frames:
        try:
            frame = mic.read(timeout=2.0)
        except queue.Empty:
            break
        speech = vad.prob(frame) >= settings.vad_threshold
        if not started:
            preroll.append(frame)
            if len(preroll) > preroll_max:
                preroll.pop(0)
            if speech:
                started = True
                collected.extend(preroll)
                collected.append(frame)
            else:
                waited += 1
                if waited >= start_limit:
                    return np.zeros(0, dtype=np.float32)
        else:
            collected.append(frame)
            if speech:
                silence = 0
            else:
                silence += 1
                if silence >= silence_limit:
                    break

    if not collected:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(collected).astype(np.float32)


def _speak_with_bargein(events, speaker, mic: MicStream, vad, settings: Settings) -> bool:
    """Speak a reply while watching for barge-in. Returns True if interrupted."""
    mic.drain()
    vad.reset()
    done = threading.Event()
    error: list[Exception] = []  # worker-thread failure, surfaced to the caller

    def _run():
        try:
            speaker.speak_events(events)
        except Exception as exc:  # noqa: BLE001
            log.exception("speak failed")
            error.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=_run, name="speak", daemon=True)
    worker.start()

    frame_ms = _frame_ms(settings, mic)
    bargein_limit = max(2, int(settings.bargein_ms / frame_ms))
    speech = 0
    barged = False

    while not done.is_set():
        try:
            frame = mic.read(timeout=0.1)
        except queue.Empty:
            continue
        # Only count barge-in once audio is actually playing.
        if not speaker.player.is_playing:
            speech = 0
            continue
        if vad.prob(frame) >= settings.vad_threshold:
            speech += 1
            if speech >= bargein_limit:
                log.info("barge-in detected — stopping playback")
                speaker.player.stop()
                barged = True
                break
        else:
            speech = 0

    done.wait()
    # A failure in the LLM/tool/TTS stream only surfaced inside the worker
    # thread; re-raise it so the caller reports the error instead of treating a
    # broken turn as a successful, non-barged one. A barge-in stop can legitimately
    # abort the worker mid-reply, so don't re-raise in that case.
    if error and not barged:
        raise error[0]
    return barged


def run_ptt(settings: Settings, assistant, speaker, stt, vad) -> int:
    """Push-to-talk: press Enter, speak, hear the reply."""
    name = settings.assistant_name
    print(f"{name} (push-to-talk). Press Enter then speak; type q + Enter to quit.\n")
    with MicStream(sample_rate=settings.mic_sample_rate, device=settings.input_device) as mic:
        while True:
            cmd = input("[Enter to talk] ").strip().lower()
            if cmd in ("q", "quit", "exit"):
                break
            print("  listening…")
            audio = capture_utterance(mic, vad, settings)
            if len(audio) == 0:
                print("  (didn't catch anything)\n")
                continue
            text = stt.transcribe(audio, settings.mic_sample_rate)
            print(f"  you: {text}")
            if not text:
                print()
                continue
            print(f"  {name.lower()}: ", end="", flush=True)
            speaker.speak_events(assistant.ask(text))
            print("\n")
    return 0
