"""VoiceService — a managed, self-healing hands-free loop.

Wraps the wake-word → listen → think → speak pipeline with:
  * pause / resume (privacy: mute the mic without quitting)
  * stop (clean shutdown)
  * state callbacks (idle/listening/thinking/speaking/paused/error) for the tray
  * per-turn error isolation + mic auto-restart, so it survives 24/7

Driven by both the tray app and the CLI ``--voice`` mode.
"""

from __future__ import annotations

import difflib
import logging
import queue
import re
import threading
import time

from .audio.capture import MicStream
from .config import Settings
from .voice_loop import _speak_with_bargein, capture_utterance

log = logging.getLogger("friday.service")

_STOP_WORDS = {"stop", "quit", "exit", "goodbye", "good bye", "shut down", "shutdown"}

# Whisper (base.en, greedy) mangles the Japanese name "Miku" a dozen ways,
# especially with a non-US accent — these are all treated as the wake word.
_MIKU_VARIANTS = frozenset({
    "miku", "mikku", "mikuu", "myku", "meeku", "meku", "mieku", "meiku",
    "miko", "mikko", "mikou", "meeko", "meekoo", "mekou", "mekoo", "meko",
    "mieko", "meikou", "niku", "nikku", "nikko", "niko", "micku", "micko",
    "mika", "meco", "meeco", "meack", "meekou",
})

# Greetings that commonly fuse onto the wake word ("heymiku", "himiku").
_GREETINGS = ("hi", "hey", "hai", "hello", "okay", "ok", "yo", "he")

# High-level states surfaced to the UI.
STATES = ("loading", "idle", "listening", "thinking", "speaking", "paused", "error", "stopped")


def _clean_command(s: str) -> str:
    return s.strip().strip(" ,.!?-—").strip()


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _is_wake_token(word: str, phrase: str) -> bool:
    """True if a single transcribed word is (a mishearing of) the wake word."""
    if len(word) < 3:
        return False
    if word == phrase:
        return True
    if phrase == "miku" and word in _MIKU_VARIANTS:
        return True
    # Fuzzy fallback for near-misses. Permissive on purpose: a rare false wake
    # just pops Miku up saying "Yes?", which beats never waking at all. Requires
    # the same first letter so unrelated words don't trigger.
    return word[0] == phrase[0] and _similar(word, phrase) >= 0.74


def match_wake_phrase(text: str, phrase: str) -> tuple[bool, str]:
    """Return (woke, trailing_command).

    Fuzzy by design: Whisper rarely transcribes "Miku" cleanly, so an exact
    substring match misses almost every real utterance. We match the wake token
    against a set of known mishearings plus a similarity threshold, and tolerate
    a fused greeting ("himiku") or a split mishearing ("mee koo").
    """
    p = (phrase or "").strip().lower()
    if not p:
        return False, ""

    raw = re.findall(r"\S+", text or "")            # original tokens (keep the command intact)
    norm = [re.sub(r"[^a-z0-9]+", "", t.lower()) for t in raw]

    # Multi-word custom phrase: normalized substring match.
    if " " in p:
        joined = " ".join(n for n in norm if n)
        if p in joined:
            return True, _clean_command(joined.split(p, 1)[1])
        return False, ""

    # Single-token wake word (the default "miku"): scan words + adjacent pairs.
    for i, w in enumerate(norm):
        if not w:
            continue
        cand = w
        for g in _GREETINGS:                        # peel a fused greeting
            if cand.startswith(g) and len(cand) >= len(g) + 3:
                cand = cand[len(g):]
                break
        if _is_wake_token(w, p) or _is_wake_token(cand, p):
            return True, _clean_command(" ".join(raw[i + 1:]))
        if i + 1 < len(norm) and _is_wake_token(w + norm[i + 1], p):
            return True, _clean_command(" ".join(raw[i + 2:]))
    return False, ""


class VoiceService:
    def __init__(self, settings: Settings, *, verbose: bool = False, on_state=None,
                 on_transcript=None, on_event=None) -> None:
        self.settings = settings
        self.verbose = verbose
        self._on_state = on_state or (lambda s: None)
        self._on_transcript = on_transcript or (lambda t: None)
        self._on_event = on_event or (lambda kind, msg: None)  # (kind, message) notifications

        self.state = "loading"
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None

        self.assistant = None
        self.speaker = None
        self.stt = None
        self.vad = None
        self.wake = None
        self.overlay = None

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="voice-service", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.speaker is not None:
            try:
                self.speaker.player.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.overlay is not None:
            try:
                self.overlay.stop()
            except Exception:  # noqa: BLE001
                pass

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        """True while the service loop thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def pause(self) -> None:
        self._paused.set()
        self._set_state("paused")

    def resume(self) -> None:
        self._paused.clear()
        self._set_state("idle")

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    # -- internals --------------------------------------------------------

    def _set_state(self, s: str) -> None:
        self.state = s
        try:
            self._on_state(s)
        except Exception:  # noqa: BLE001
            log.debug("on_state callback failed", exc_info=True)
        # Drive the Miku mascot. Any active state *shows* her (show is
        # idempotent: already visible -> just a state change) so a thinking/
        # speaking transition while hidden — timer announcements, a restarted
        # mascot — still brings her up.
        if self.overlay is not None:
            try:
                if s in ("listening", "thinking", "speaking"):
                    self.overlay.show(s)
                elif s in ("idle", "paused", "error", "stopped"):
                    self.overlay.hide()
            except Exception:  # noqa: BLE001
                log.debug("overlay update failed", exc_info=True)

    def _print(self, *a, **k) -> None:
        if self.verbose:
            print(*a, **k)

    def _build(self) -> None:
        from .assistant import Assistant
        from .audio.playback import AudioPlayer
        from .llm.openrouter_llm import OpenRouterEngine
        from .skills import build_default_registry
        from .speech import Speaker
        from .stt.faster_whisper_stt import FasterWhisperSTT
        from .tts import build_tts_engine
        from .vad import SileroVad
        from .wakeword import WakeWord

        s = self.settings
        if not s.has_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")

        tts = build_tts_engine(s)
        player = AudioPlayer(device=s.output_device)
        on_text = (lambda t: print(t, end="", flush=True)) if self.verbose else (lambda t: None)
        self.speaker = Speaker(tts, player, min_chars=s.tts_min_chars, on_text=on_text)

        registry = build_default_registry(on_timer_fire=self._announce_timer, settings=s)
        self.assistant = Assistant(s, OpenRouterEngine(s, dispatch=registry.dispatch), registry)

        self.stt = FasterWhisperSTT(s.stt_model, s.stt_compute_type, s.stt_cpu_threads)
        self.vad = SileroVad(threshold=s.vad_threshold, sample_rate=s.mic_sample_rate)

        # Wake: openWakeWord model, or STT phrase-spotting (custom phrase like "hi miku").
        if s.wake_mode.lower() != "stt":
            self.wake = WakeWord(s.wake_model, s.wake_threshold)

        if s.enable_overlay:
            try:
                from .overlay import OverlayClient

                self.overlay = OverlayClient(settings=s)
            except Exception as exc:  # noqa: BLE001
                log.warning("Miku overlay unavailable: %s", exc)

    def _announce_timer(self, msg: str) -> None:
        self._on_event("timer", msg)
        if self.speaker is not None:
            try:
                self.speaker.say_text(msg)
            except Exception:  # noqa: BLE001
                log.exception("failed to speak timer alert")

    def _run(self) -> None:
        try:
            self._set_state("loading")
            self._build()
        except Exception as exc:  # noqa: BLE001
            log.exception("failed to start voice service")
            self._set_state("error")
            self._on_event("error", f"Startup failed: {exc}")
            return

        if self.settings.startup_greeting:
            try:
                self.speaker.say_text(f"{self.settings.assistant_name} online.")
            except Exception:  # noqa: BLE001
                pass

        # Outer loop restarts the mic stream if the device drops.
        while not self._stop.is_set():
            try:
                self._loop_once_open()
            except Exception as exc:  # noqa: BLE001
                log.exception("voice loop error; restarting mic in 3s")
                self._on_event("error", f"Audio error, retrying: {exc}")
                self._set_state("error")
                if self._stop.wait(3.0):
                    break
        self._set_state("stopped")

    def _loop_once_open(self) -> None:
        s = self.settings
        stt_wake = s.wake_mode.lower() == "stt"
        with MicStream(sample_rate=s.mic_sample_rate, device=s.input_device) as mic:
            while not self._stop.is_set():
                if stt_wake:
                    woke, command = self._stt_wake(mic)
                else:
                    woke, command = self._wait_for_wake(mic), ""
                if self._stop.is_set():
                    return
                if not woke:
                    continue
                self._set_state("listening")  # Miku peeks up
                self._on_event("wake", "Listening…")
                try:
                    self._run_turn(mic, command)
                except Exception as exc:  # noqa: BLE001
                    log.exception("turn failed")
                    self._on_event("error", f"Turn failed: {exc}")
                self._set_state("idle")  # Miku slides away

    def _wait_for_wake(self, mic: MicStream) -> bool:
        """Return True on wake, False if stopped. Respects pause."""
        self.wake.reset()
        mic.drain()
        if self.state not in ("paused",):
            self._set_state("idle")
        while not self._stop.is_set():
            if self._paused.is_set():
                if self.state != "paused":
                    self._set_state("paused")
                mic.drain()
                time.sleep(0.2)
                continue
            if self.state == "paused":  # just resumed
                self._set_state("idle")
                self.wake.reset()
            try:
                frame = mic.read(timeout=0.5)
            except queue.Empty:
                continue
            if self.wake.triggered(MicStream.to_int16(frame)):
                return True
        return False

    def _stt_wake(self, mic: MicStream) -> tuple[bool, str]:
        """Listen for the wake phrase via short STT windows (custom 'hi miku').

        Returns (woke, trailing_command). If the user said the phrase followed by
        a command in one breath ("hi miku, what's the weather"), the command is
        returned so we skip the "Yes?" round-trip.
        """
        phrase = (self.settings.wake_phrase or "miku").strip().lower()
        self._set_state("idle")
        while not self._stop.is_set():
            if self._paused.is_set():
                if self.state != "paused":
                    self._set_state("paused")
                mic.drain()
                time.sleep(0.2)
                continue
            if self.state == "paused":
                self._set_state("idle")
            # short start-timeout so we re-check pause/stop ~ every 2s
            audio = capture_utterance(mic, self.vad, self.settings, start_timeout_s=2.0)
            if len(audio) == 0:
                continue
            text, avg_lp, no_speech, comp = self.stt.transcribe_scored(
                audio, self.settings.mic_sample_rate
            )
            if not text.strip():
                continue
            # Reject Whisper hallucinations on non-speech (fan noise, silence):
            # low decode confidence, high no-speech prob, or repetitive gibberish.
            if no_speech > 0.7 or avg_lp < -1.2 or comp > 2.6:
                log.debug("ignored non-speech %r (lp=%.2f ns=%.2f cr=%.2f)",
                          text, avg_lp, no_speech, comp)
                continue
            woke, rest = match_wake_phrase(text, phrase)
            # Visible so wake mishears can be diagnosed and tuned.
            log.info("wake-listen heard %r -> wake=%s", text, woke)
            if woke:
                return True, rest
        return False, ""

    def _run_turn(self, mic: MicStream, command_text: str) -> None:
        # A turn may chain: if the user barges in over the reply, the
        # interruption is captured immediately as the next command (no wake
        # word needed) instead of being thrown away.
        followup = self._run_exchange(mic, command_text)
        while followup and not self._stop.is_set():
            self._set_state("listening")
            followup = self._run_exchange(mic, "", prompt=False)

    def _run_exchange(self, mic: MicStream, command_text: str, *, prompt: bool = True) -> bool:
        """One command -> reply. Returns True if the user interrupted the reply
        (caller should immediately listen for the follow-up, without a prompt —
        the user is already mid-sentence)."""
        s = self.settings
        command_text = (command_text or "").strip()

        if not command_text:
            if prompt:
                # Wake acknowledged — instant cached "Yes?" — then capture the command.
                try:
                    self.speaker.say_text("Yes?")
                except Exception:  # noqa: BLE001
                    pass
            audio = capture_utterance(mic, self.vad, s)
            if len(audio) == 0:
                return False
            self._set_state("thinking")
            command_text = self.stt.transcribe(audio, s.mic_sample_rate)
        else:
            self._set_state("thinking")

        self._print(f"  you: {command_text}")
        self._on_transcript(command_text)
        if not command_text:
            return False
        if command_text.strip(" .!?").lower() in _STOP_WORDS:
            try:
                self.speaker.say_text("Pausing. Say the wake word when you need me.")
            except Exception:  # noqa: BLE001
                pass
            self.pause()
            return False

        self._set_state("speaking")
        return _speak_with_bargein(self.assistant.ask(command_text), self.speaker, mic, self.vad, s)
