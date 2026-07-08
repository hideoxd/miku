"""FRIDAY entry point.

Phase 0 modes:
  python -m friday.main --text       interactive text chat (needs OPENROUTER_API_KEY)
  python -m friday.main --selftest    offline check of tools + chunker (no key needed)

Later phases add --voice (full hands-free loop) and --ptt (push-to-talk).
"""

from __future__ import annotations

import argparse
import logging
import sys

from .assistant import Assistant
from .config import get_settings
from .llm.base import TextDelta, ToolActivity
from .llm.chunker import SentenceChunker
from .logging_setup import setup_logging
from .skills import build_default_registry

log = logging.getLogger("friday.main")


def _enable_utf8() -> None:
    """Windows consoles default to cp1252 and crash on non-ASCII output.
    Force UTF-8 on the std streams so glyphs degrade to boxes instead of errors."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _build_speaker(settings):
    """Build the TTS + player + Speaker, or return None if audio is unavailable."""
    from .audio.playback import AudioPlayer
    from .speech import Speaker
    from .tts import build_tts_engine

    tts = build_tts_engine(settings)
    player = AudioPlayer(device=settings.output_device)
    speaker = Speaker(
        tts,
        player,
        min_chars=settings.tts_min_chars,
        on_text=lambda t: print(t, end="", flush=True),
        on_tool=lambda name: print(f"\n  … using {name}\n  ", end="", flush=True),
    )
    return speaker


def _make_assistant(settings, registry):
    """Build the Assistant, or None if no API key is configured."""
    if not settings.has_api_key:
        return None
    from .llm.openrouter_llm import OpenRouterEngine

    engine = OpenRouterEngine(settings, dispatch=registry.dispatch)
    return Assistant(settings, engine, registry)


def run_voice_mode(hands_free: bool) -> int:
    """Push-to-talk (--ptt) or hands-free wake-word loop (--voice)."""
    settings = get_settings()
    if not settings.has_api_key:
        print("No OPENROUTER_API_KEY found — add it to .env first.")
        return 1

    if hands_free:
        from .service import VoiceService

        print("Loading… once ready, say the wake word then speak. Ctrl+C to quit.")
        service = VoiceService(
            settings,
            verbose=True,
            on_event=lambda kind, msg: print(f"  [{msg}]"),
        )
        service.start()
        try:
            while service._thread and service._thread.is_alive():
                service.join(0.5)
        except KeyboardInterrupt:
            print("\n(stopping)")
            service.stop()
            service.join(5)
        return 0

    # Push-to-talk path
    try:
        speaker = _build_speaker(settings)
    except Exception as exc:  # noqa: BLE001
        print(f"[voice output unavailable: {exc}]")
        return 1

    def announce_timer(msg: str) -> None:
        try:
            speaker.say_text(msg)
        except Exception:  # noqa: BLE001
            log.exception("failed to speak timer alert")

    registry = build_default_registry(on_timer_fire=announce_timer)
    assistant = _make_assistant(settings, registry)

    from .stt.faster_whisper_stt import FasterWhisperSTT
    from .vad import SileroVad
    from .voice_loop import run_ptt

    print("Loading speech models… (first run downloads them)")
    stt = FasterWhisperSTT(
        settings.stt_model, settings.stt_compute_type, settings.stt_cpu_threads
    )
    vad = SileroVad(threshold=settings.vad_threshold, sample_rate=settings.mic_sample_rate)
    return run_ptt(settings, assistant, speaker, stt, vad)


def run_autostart(action: str) -> int:
    from . import autostart

    if action == "install":
        path = autostart.install()
        print(f"Auto-start installed — FRIDAY will launch hidden at every login.\n  {path}")
    elif action == "uninstall":
        removed = autostart.uninstall()
        print("Auto-start removed." if removed else "Auto-start was not installed.")
    else:  # status
        st = autostart.status()
        print(f"Auto-start installed: {st['installed']}")
        print(f"  launcher: {st['launcher']}")
        print(f"  runs:     {st['pythonw']} -m friday.tray  (cwd {st['cwd']})")
    return 0


def run_text_repl(speak: bool = False) -> int:
    settings = get_settings()

    speaker = None
    if speak:
        try:
            speaker = _build_speaker(settings)
        except Exception as exc:  # noqa: BLE001
            log.warning("voice output disabled: %s", exc)
            print(f"[voice output unavailable: {exc}] — continuing in text-only mode.\n")

    def announce_timer(msg: str) -> None:
        print(f"\n\a[{settings.assistant_name}] {msg}")
        if speaker is not None:
            try:
                speaker.say_text(msg)
            except Exception:  # noqa: BLE001
                log.exception("failed to speak timer alert")

    registry = build_default_registry(on_timer_fire=announce_timer)

    if not settings.has_api_key:
        print(
            "No OPENROUTER_API_KEY found.\n"
            "  1. Copy .env.example to .env\n"
            "  2. Add your key from https://openrouter.ai/keys\n"
            "Then rerun. (Try `--selftest` to check tools without a key.)"
        )
        return 1

    assistant = _make_assistant(settings, registry)

    voice_note = f", voice: {settings.tts_engine}" if speaker else ""
    print(f"{settings.assistant_name} ready (model: {settings.llm_model}{voice_note}).")
    print("Type your message. Commands: /reset, /quit\n")

    while True:
        try:
            user = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user in ("/quit", "/exit"):
            break
        if user == "/reset":
            assistant.reset()
            print("(conversation reset)\n")
            continue

        print(f"{settings.assistant_name.lower()} › ", end="", flush=True)
        try:
            if speaker is not None:
                speaker.speak_events(assistant.ask(user))
            else:
                for event in assistant.ask(user):
                    if isinstance(event, TextDelta):
                        print(event.text, end="", flush=True)
                    elif isinstance(event, ToolActivity):
                        print(f"\n  … using {event.name}\n  ", end="", flush=True)
        except Exception as exc:  # noqa: BLE001
            log.exception("turn failed")
            print(f"\n[error: {exc}]")
        print("\n")

    print("Goodbye.")
    return 0


def run_tts_selftest(text: str, play: bool) -> int:
    """Synthesize a line to a WAV (and optionally play it). No API key needed."""
    from .audio.playback import write_wav
    from .config import ROOT
    from .tts import build_tts_engine

    settings = get_settings()
    print(f"TTS engine: {settings.tts_engine} (voice: {settings.tts_voice or 'default'})")
    engine = build_tts_engine(settings)

    import time

    t0 = time.perf_counter()
    pcm = engine.synthesize(text)
    dt = time.perf_counter() - t0

    if pcm is None or len(pcm) == 0:
        print("FAIL: engine returned no audio.")
        return 1

    duration = len(pcm) / engine.sample_rate
    out_dir = ROOT / "cache"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "tts_selftest.wav"
    write_wav(str(out), pcm, engine.sample_rate)
    rtf = dt / duration if duration else float("inf")
    print(
        f"synthesized {len(pcm)} samples · {duration:.2f}s audio @ {engine.sample_rate} Hz · "
        f"synth {dt:.2f}s (RTF {rtf:.2f})"
    )
    print(f"wrote {out}")

    if play:
        try:
            from .audio.playback import AudioPlayer

            player = AudioPlayer(device=settings.output_device)
            print("playing… (you should hear it)")
            player.enqueue(pcm, engine.sample_rate)
            player.wait_done()
        except Exception as exc:  # noqa: BLE001
            print(f"[playback unavailable: {exc}] — the WAV is still on disk.")

    print("tts-selftest: PASS")
    return 0


def run_selftest() -> int:
    """Exercise tool dispatch + sentence chunking without any network/API key."""
    print("== FRIDAY self-test (offline) ==\n")
    registry = build_default_registry()

    print("Registered tools:")
    for t in registry.tools_schema():
        print(f"  - {t['function']['name']}: {t['function']['description']}")
    print()

    print("dispatch get_current_datetime →")
    print("  ", registry.dispatch("get_current_datetime", "{}"))

    print("dispatch set_timer(2s, 'tea') →")
    print("  ", registry.dispatch("set_timer", '{"seconds": 2, "label": "tea"}'))
    print("dispatch list_timers →")
    print("  ", registry.dispatch("list_timers", "{}"))
    print("dispatch cancel_timer('tea') →")
    print("  ", registry.dispatch("cancel_timer", '{"label": "tea"}'))
    print("dispatch unknown_tool →")
    print("  ", registry.dispatch("unknown_tool", "{}"))
    print()

    print("Sentence chunker on a streamed reply:")
    chunker = SentenceChunker()
    stream = ["Hello there. ", "I am FRIDAY", ", your assistant. ", "How can I help you today? ", "Bye"]
    spoken: list[str] = []
    for piece in stream:
        for sentence in chunker.feed(piece):
            spoken.append(sentence)
            print(f"  speak → {sentence!r}")
    tail = chunker.flush()
    if tail:
        spoken.append(tail)
        print(f"  speak → {tail!r} (flushed)")

    ok = len(spoken) >= 3
    print("\nself-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="friday", description="FRIDAY voice assistant")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--text", action="store_true", help="interactive text chat (default)")
    mode.add_argument("--selftest", action="store_true", help="offline tools/chunker check")
    mode.add_argument(
        "--tts-selftest",
        metavar="TEXT",
        nargs="?",
        const="Hello, I am FRIDAY. Your voice pipeline is working.",
        help="synthesize a line to cache/tts_selftest.wav (no API key needed)",
    )
    mode.add_argument("--ptt", action="store_true", help="push-to-talk voice (Enter, then speak)")
    mode.add_argument("--voice", action="store_true", help="hands-free wake-word voice loop")
    mode.add_argument("--tray", action="store_true", help="run hidden in the system tray")
    mode.add_argument("--install-autostart", action="store_true", help="launch FRIDAY at login")
    mode.add_argument("--uninstall-autostart", action="store_true", help="stop launching at login")
    mode.add_argument("--autostart-status", action="store_true", help="show auto-start status")
    parser.add_argument("--speak", action="store_true", help="speak replies aloud (with --text)")
    parser.add_argument("--play", action="store_true", help="also play audio (with --tts-selftest)")
    args = parser.parse_args(argv)

    _enable_utf8()
    settings = get_settings()
    setup_logging(settings.log_level)

    if args.selftest:
        return run_selftest()
    if args.tts_selftest is not None:
        return run_tts_selftest(args.tts_selftest, play=args.play)
    if args.tray:
        from .tray import main as tray_main

        return tray_main()
    if args.install_autostart:
        return run_autostart("install")
    if args.uninstall_autostart:
        return run_autostart("uninstall")
    if args.autostart_status:
        return run_autostart("status")
    if args.voice:
        return run_voice_mode(hands_free=True)
    if args.ptt:
        return run_voice_mode(hands_free=False)
    return run_text_repl(speak=args.speak)


if __name__ == "__main__":
    sys.exit(main())
