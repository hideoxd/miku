"""Speak a streamed LLM reply, sentence by sentence.

Ties the pieces together: assistant token stream -> SentenceChunker -> TTS ->
AudioPlayer. Each finished sentence is synthesized and queued while the LLM is
still generating the rest, and while earlier sentences are still playing — the
big perceived-latency win. Also records the latency dashboard the plan calls for
(first token, first audio).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .audio.playback import AudioPlayer
from .llm.base import StreamEvent, TextDelta, ToolActivity
from .llm.chunker import SentenceChunker
from .tts.base import TTSEngine

log = logging.getLogger("friday.speech")


@dataclass
class TurnTiming:
    first_token_s: float | None = None  # request -> first text token
    first_audio_s: float | None = None  # request -> first sentence synthesized
    total_s: float | None = None        # request -> playback finished
    sentences: int = 0
    synth_times: list[float] = field(default_factory=list)

    def summary(self) -> str:
        def fmt(v):
            return f"{v:.2f}s" if v is not None else "—"

        synth = (sum(self.synth_times) / len(self.synth_times)) if self.synth_times else None
        return (
            f"first-token {fmt(self.first_token_s)} · first-audio {fmt(self.first_audio_s)} · "
            f"total {fmt(self.total_s)} · {self.sentences} sentence(s) · "
            f"avg synth {fmt(synth)}"
        )


class Speaker:
    def __init__(
        self,
        tts: TTSEngine,
        player: AudioPlayer,
        *,
        min_chars: int = 25,
        on_text: Callable[[str], None] | None = None,
        on_tool: Callable[[str], None] | None = None,
    ) -> None:
        self.tts = tts
        self.player = player
        self.min_chars = min_chars
        self.on_text = on_text
        self.on_tool = on_tool

    def speak_events(self, events: Iterable[StreamEvent]) -> TurnTiming:
        """Consume a reply stream and speak it.

        Fast local engines speak sentence-by-sentence as they stream in. Remote
        engines that set ``prefers_full_text`` (Miku/GPT-SoVITS — each call has a
        large GPU-allocation cost) buffer the whole reply and synthesize once.
        """
        full_text = getattr(self.tts, "prefers_full_text", False)
        chunker = SentenceChunker(self.min_chars)
        buffer: list[str] = []
        timing = TurnTiming()
        t0 = time.perf_counter()

        for event in events:
            if isinstance(event, TextDelta):
                if timing.first_token_s is None:
                    timing.first_token_s = time.perf_counter() - t0
                if self.on_text:
                    self.on_text(event.text)
                if full_text:
                    buffer.append(event.text)
                else:
                    for sentence in chunker.feed(event.text):
                        self._say(sentence, timing, t0)
            elif isinstance(event, ToolActivity):
                # Nothing spoken; surface tool use to the console/logs.
                log.debug("tool activity: %s", event.name)
                if self.on_tool:
                    self.on_tool(event.name)

        tail = "".join(buffer).strip() if full_text else chunker.flush()
        if tail:
            self._say(tail, timing, t0)

        self.player.wait_done()
        timing.total_s = time.perf_counter() - t0
        log.info("⏱  turn: %s", timing.summary())
        return timing

    def say_text(self, text: str) -> TurnTiming:
        """Speak a fixed string (e.g. a greeting or a timer alert)."""
        timing = TurnTiming()
        t0 = time.perf_counter()
        for sentence in _split_plain(text, self.min_chars):
            self._say(sentence, timing, t0)
        self.player.wait_done()
        timing.total_s = time.perf_counter() - t0
        return timing

    def _say(self, sentence: str, timing: TurnTiming, t0: float) -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        ts = time.perf_counter()
        pcm = self.tts.synthesize(sentence)
        timing.synth_times.append(time.perf_counter() - ts)
        if timing.first_audio_s is None:
            timing.first_audio_s = time.perf_counter() - t0
        timing.sentences += 1
        self.player.enqueue(pcm, self.tts.sample_rate)


def _split_plain(text: str, min_chars: int) -> list[str]:
    chunker = SentenceChunker(min_chars)
    out = list(chunker.feed(text))
    tail = chunker.flush()
    if tail:
        out.append(tail)
    return out
