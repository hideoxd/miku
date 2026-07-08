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


def _announce_timer(msg: str) -> None:
    # Phase 0: just surface it. Phase 1+ routes this through TTS.
    print(f"\n\a[FRIDAY] {msg}")


def run_text_repl() -> int:
    settings = get_settings()
    registry = build_default_registry(on_timer_fire=_announce_timer)

    if not settings.has_api_key:
        print(
            "No OPENROUTER_API_KEY found.\n"
            "  1. Copy .env.example to .env\n"
            "  2. Add your key from https://openrouter.ai/keys\n"
            "Then rerun. (Try `--selftest` to check tools without a key.)"
        )
        return 1

    from .llm.openrouter_llm import OpenRouterEngine

    engine = OpenRouterEngine(settings, dispatch=registry.dispatch)
    assistant = Assistant(settings, engine, registry)

    print(f"{settings.assistant_name} ready (model: {settings.llm_model}).")
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
    args = parser.parse_args(argv)

    _enable_utf8()
    settings = get_settings()
    setup_logging(settings.log_level)

    if args.selftest:
        return run_selftest()
    return run_text_repl()


if __name__ == "__main__":
    sys.exit(main())
