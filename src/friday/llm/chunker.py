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
        """Add streamed text; return any complete sentences now ready to speak."""
        self._buf += text
        out: list[str] = []
        while True:
            m = self._last_boundary(self._buf)
            if m is None:
                break
            end = m.end()
            sentence = self._buf[:end].strip()
            rest = self._buf[end:]
            # Only emit if it's substantial and not a false abbreviation split.
            if len(sentence) < self.min_chars or _ABBREV.search(sentence):
                # keep waiting for more text unless there's clearly more sentence after
                if not rest.strip():
                    break
            out.append(sentence)
            self._buf = rest
        return out

    def flush(self) -> str:
        """Return whatever remains (call at end of stream)."""
        rest = self._buf.strip()
        self._buf = ""
        return rest

    @staticmethod
    def _last_boundary(text: str):
        """First sentence-ending punctuation followed by space/newline or EOS."""
        for m in _ENDING.finditer(text):
            after = text[m.end() : m.end() + 1]
            if after == "" or after.isspace():
                return m
        return None
