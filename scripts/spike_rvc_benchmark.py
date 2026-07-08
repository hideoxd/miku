"""RVC/Miku voice spike — de-risk the highest-uncertainty component first.

Calls your duplicated Hugging Face "mikuTTS" Space via gradio_client on a few
sample sentences, measures WARM round-trip latency, and saves the returned wavs
so you can judge Miku-likeness for an English vs Japanese base voice.

Setup:
    pip install gradio_client
    # Duplicate https://huggingface.co/spaces/NoCrypt/mikuTTS into your account.
    set HF_HUB_ENABLE_HF_TRANSFER=0
    python scripts/spike_rvc_benchmark.py --space <your-hf-user>/mikuTTS

Notes:
- The exact api_name and argument order differ between Space forks. This script
  prints the Space's API (via .view_api()) first — if the predict() call fails,
  copy the real signature from that printout into `call_space()` below.
- First call is a cold start (can be tens of seconds). Latency numbers reported
  here are the WARM calls (cold start is excluded from the average).
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

# The public NoCrypt/mikuTTS Space currently errors on hf_transfer downloads.
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

OUT_DIR = Path(__file__).resolve().parents[1] / "cache" / "spike"

SENTENCES = [
    ("short", "Yes? How can I help?"),
    ("medium", "The meeting is at three, and it looks like rain later today."),
    ("long", "Good morning. You have two events today, a light drizzle this afternoon, "
             "and I have already started your coffee timer for five minutes."),
]


def call_space(client, text: str, lang: str):
    """Invoke the Space. ADJUST arg names/order to match your fork's view_api()."""
    # Common NoCrypt/mikuTTS-style signature: (text, voice, ...). Japanese voice
    # tends to sound more Miku-like; English is more intelligible for commands.
    voice = "ja-JP-NanamiNeural" if lang == "ja" else "en-US-AriaNeural"
    return client.predict(
        text,       # text to speak
        voice,      # edge-tts base voice
        0,          # pitch (semitones)
        api_name="/predict",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark the cloud Miku voice path")
    ap.add_argument("--space", required=True, help="HF Space id, e.g. you/mikuTTS")
    ap.add_argument("--langs", nargs="+", default=["ja", "en"], choices=["ja", "en"])
    ap.add_argument("--warm", type=int, default=3, help="warm calls per sentence")
    args = ap.parse_args(argv)

    try:
        from gradio_client import Client
    except ImportError:
        print("Install the client first:  pip install gradio_client")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Connecting to Space: {args.space} …")
    client = Client(args.space)

    print("\n=== Space API (use this if predict() below fails) ===")
    try:
        print(client.view_api(print_info=False))
    except Exception as exc:  # noqa: BLE001
        print(f"(view_api failed: {exc})")
    print("=" * 55)

    for lang in args.langs:
        print(f"\n--- base voice: {lang} ---")
        # One cold call (discarded) to warm the Space.
        try:
            call_space(client, "Warming up.", lang)
        except Exception as exc:  # noqa: BLE001
            print(f"  cold call failed — fix call_space() to match view_api(): {exc}")
            return 2

        for tag, text in SENTENCES:
            timings: list[float] = []
            last = None
            for _ in range(args.warm):
                t0 = time.perf_counter()
                try:
                    last = call_space(client, text, lang)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{tag}] call failed: {exc}")
                    break
                timings.append(time.perf_counter() - t0)
            if timings:
                avg = statistics.mean(timings)
                out = _save(last, OUT_DIR / f"{lang}_{tag}.wav")
                print(f"  [{tag:6}] warm avg {avg:5.2f}s  ({len(text)} chars) → {out}")

    print("\nDone. Listen to the wavs in cache/spike/ and pick the base voice that")
    print("sounds most like Miku with acceptable latency. Update FRIDAY_BASE_VOICE_LANG.")
    return 0


def _save(result, dest: Path) -> str:
    """gradio predict() returns a filepath (or tuple containing one). Copy it out."""
    import shutil

    path = result
    if isinstance(result, (list, tuple)):
        path = next((p for p in result if isinstance(p, str) and p.endswith((".wav", ".mp3"))), result[0])
    try:
        shutil.copyfile(path, dest)
        return str(dest)
    except Exception:  # noqa: BLE001
        return f"(returned: {result!r})"


if __name__ == "__main__":
    sys.exit(main())
