"""Turn a token stream into speakable sentences.

Phase 1+ feeds each completed sentence to TTS while the LLM is still generating
the rest — the single biggest perceived-latency win. Built and unit-testable now.
"""

from __future__ import annotations

import re

# End of sentence: . ! ? … possibly followed by a closing quote/bracket.
_ENDING = re.compile(r'[.!?…]+["\')\]]?')
# Avoid splitting common abbreviations / decimals right before the boundary.
_ABBREV = re.compile(r"\b(?:mr|mrs|ms|dr|st|vs|e\.g|i\.e|etc|no)\.$", re.IGNORECASE)


class SentenceChunker:
    def __init__(self, min_chars: int = 25) -> None:
        self.min_chars = min_chars
        self._buf = ""

    def feed(self, text: str) -> list[str]:
        """Add streamed text; return any complete sentences now ready to speak.

        A chunk shorter than ``min_chars`` (or ending in an abbreviation) is
        never emitted on its own — it extends to the next sentence boundary, so
        TTS isn't fed choppy fragments like "Hi." as separate utterances.
        """
        self._buf += text
        out: list[str] = []
        while True:
            chunk = self._next_chunk()
            if chunk is None:
                break
            out.append(chunk)
        return out

    def _next_chunk(self) -> str | None:
        """Earliest speakable prefix of the buffer, consumed; None if not ready."""
        for m in _ENDING.finditer(self._buf):
            after = self._buf[m.end() : m.end() + 1]
            if after != "" and not after.isspace():
                continue  # inside a word/number (e.g. a decimal point)
            sentence = self._buf[: m.end()].strip()
            if len(sentence) < self.min_chars or _ABBREV.search(sentence):
                continue  # too short / abbreviation — grow to the next boundary
            self._buf = self._buf[m.end() :]
            return sentence
        return None

    def flush(self) -> str:
        """Return whatever remains (call at end of stream)."""
        rest = self._buf.strip()
        self._buf = ""
        return rest
