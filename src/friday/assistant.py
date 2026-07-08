"""The brain orchestrator: conversation state + streaming replies.

Phase 0 uses this from a text REPL. Phases 1-3 reuse it unchanged — STT feeds
:meth:`Assistant.ask`, and the streamed ``TextDelta`` events are sent to TTS
instead of the console.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from .config import Settings
from .llm.base import LLMEngine, Message, StreamEvent, TextDelta, ToolActivity
from .skills import SkillRegistry

log = logging.getLogger("friday.assistant")

_PROMPT_PATH = Path(__file__).parent / "prompts" / "system.txt"


class Assistant:
    def __init__(self, settings: Settings, engine: LLMEngine, registry: SkillRegistry) -> None:
        self.settings = settings
        self.engine = engine
        self.registry = registry
        self.messages: list[Message] = [{"role": "system", "content": self._system_prompt()}]

    def _system_prompt(self) -> str:
        try:
            return _PROMPT_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return f"You are {self.settings.assistant_name}, a helpful spoken assistant."

    def ask(self, user_text: str) -> Iterator[StreamEvent]:
        """Add a user turn and stream the reply, running tools transparently.

        Yields ``TextDelta`` (speak/print) and ``ToolActivity`` (status). The
        full assistant text is appended to history when the stream ends.
        """
        self.messages.append({"role": "user", "content": user_text})
        tools = self.registry.tools_schema()

        collected: list[str] = []
        for event in self.engine.stream(self.messages, tools):
            if isinstance(event, TextDelta):
                collected.append(event.text)
            elif isinstance(event, ToolActivity):
                log.info("tool → %s(%s)", event.name, event.arguments)
            yield event

        final = "".join(collected).strip()
        if final:
            self.messages.append({"role": "assistant", "content": final})

    def reset(self) -> None:
        """Clear the conversation, keeping the system prompt."""
        self.messages = [self.messages[0]]
