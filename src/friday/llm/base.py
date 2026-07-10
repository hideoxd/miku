"""LLM engine interface + shared message/streaming types.

The rest of FRIDAY depends only on this Protocol, so the OpenRouter engine can
be swapped for a local model (Ollama, etc.) later without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Protocol, runtime_checkable

# A chat message is the OpenAI-style dict: {"role", "content", ...}.
Message = dict[str, Any]
# A tool schema is the OpenAI function-tool dict.
ToolSchema = dict[str, Any]


@dataclass
class TextDelta:
    """A chunk of assistant text as it streams in."""

    text: str


@dataclass
class ToolActivity:
    """Emitted when the model decides to call a tool (for logging/UX)."""

    name: str
    arguments: str


# A streamed reply yields TextDelta (speak these) and ToolActivity (status).
StreamEvent = TextDelta | ToolActivity


@runtime_checkable
class LLMEngine(Protocol):
    """A streaming, tool-calling chat engine."""

    def stream(
        self,
        messages: Iterable[Message],
        tools: list[ToolSchema] | None = None,
        out_history: list[Message] | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream a reply, transparently running any tool calls to completion.

        Yields ``TextDelta`` for spoken text and ``ToolActivity`` for tool use.
        Implementations mutate nothing the caller owns; conversation history is
        managed by the caller. If ``out_history`` is given, the engine appends
        every tool round-trip message (the assistant tool-call turn and the tool
        results) to it so the caller can persist them in its history — without
        them, the model forgets on the next turn which tools it called and what
        they returned.
        """
        ...
