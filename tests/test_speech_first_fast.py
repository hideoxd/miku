"""First-sentence-fast: engines that prefer full text still start audio early.

Miku/GPT-SoVITS set ``prefers_full_text`` because each cloud-GPU call is costly.
Rather than buffering the *entire* reply before any audio (old behavior), the
Speaker synthesizes the first completed sentence immediately and batches the
rest into one call — cutting first-audio latency to ~one sentence while keeping
the round-trips to two per turn.
"""

from __future__ import annotations

import numpy as np

from friday.llm.base import TextDelta
from friday.speech import Speaker


class _FakeEngine:
    sample_rate = 40_000

    def __init__(self, prefers_full_text: bool) -> None:
        self.prefers_full_text = prefers_full_text
        self.calls: list[str] = []

    def synthesize(self, text: str) -> np.ndarray:
        self.calls.append(text)
        return np.zeros(1, dtype=np.float32)


class _FakePlayer:
    def enqueue(self, pcm, sample_rate) -> None:  # noqa: ANN001
        pass

    def wait_done(self) -> None:
        pass


_REPLY = [
    TextDelta("Hello there, how are you today? "),
    TextDelta("I am doing quite well, thanks. "),
    TextDelta("Take care and goodbye now."),
]


def test_full_text_engine_speaks_first_sentence_then_batches():
    eng = _FakeEngine(prefers_full_text=True)
    timing = Speaker(eng, _FakePlayer()).speak_events(iter(_REPLY))

    # Exactly two cloud calls: the fast first sentence, then the batched rest.
    assert len(eng.calls) == 2
    assert eng.calls[0] == "Hello there, how are you today?"
    assert "well" in eng.calls[1].lower() and "goodbye" in eng.calls[1].lower()
    assert timing.first_audio_s is not None
    assert timing.sentences == 2


def test_streaming_engine_still_speaks_each_sentence():
    eng = _FakeEngine(prefers_full_text=False)
    Speaker(eng, _FakePlayer()).speak_events(iter(_REPLY))

    # Local engines keep the per-sentence cadence (3 sentences -> 3 calls).
    assert len(eng.calls) == 3
    assert eng.calls[0] == "Hello there, how are you today?"
