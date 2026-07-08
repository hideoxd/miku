"""OpenRouter brain: streaming chat + a transparent function-calling loop.

OpenRouter is OpenAI-compatible, so we use the official ``openai`` SDK pointed
at OpenRouter's base URL. The model, and therefore the whole brain, is swappable
via one env var (``FRIDAY_LLM_MODEL``).
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable, Iterator

from openai import OpenAI

from ..config import Settings
from .base import LLMEngine, Message, StreamEvent, TextDelta, ToolActivity, ToolSchema

log = logging.getLogger("friday.llm")

# Called with (tool_name, json_arguments) -> string result fed back to the model.
DispatchFn = Callable[[str, str], str]


class OpenRouterEngine(LLMEngine):
    def __init__(self, settings: Settings, dispatch: DispatchFn) -> None:
        if not settings.has_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self.settings = settings
        self.dispatch = dispatch
        self.client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            # OpenRouter attribution headers (optional but recommended).
            default_headers={
                "HTTP-Referer": settings.app_url,
                "X-Title": settings.app_title,
            },
        )

    def stream(
        self,
        messages: Iterable[Message],
        tools: list[ToolSchema] | None = None,
    ) -> Iterator[StreamEvent]:
        # Work on our own copy so we can append tool round-trips without
        # clobbering the caller's history (the caller appends the final text).
        convo: list[Message] = list(messages)
        tools = tools or None

        for _round in range(self.settings.max_tool_rounds):
            # ``out`` is filled in by the inner generator as it drains the stream.
            out: dict[str, object] = {"tool_calls": [], "finish": None}
            yield from self._one_call(convo, tools, out)

            tool_calls = out["tool_calls"]  # type: ignore[assignment]
            if out["finish"] != "tool_calls" or not tool_calls:
                return  # normal completion

            # Record the assistant's tool-call turn, then run each tool.
            convo.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                yield ToolActivity(name=tc["name"], arguments=tc["arguments"])
                result = self.dispatch(tc["name"], tc["arguments"])
                convo.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": result}
                )

        log.warning("hit max_tool_rounds (%d); stopping tool loop", self.settings.max_tool_rounds)

    # -- internals --------------------------------------------------------

    def _one_call(
        self,
        convo: list[Message],
        tools: list[ToolSchema] | None,
        out: dict[str, object],
    ) -> Iterator[StreamEvent]:
        """One streaming completion: yields text deltas live, stashes tool
        calls + finish_reason into ``out`` for the caller's loop."""
        kwargs = dict(
            model=self.settings.llm_model,
            messages=convo,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = self.client.chat.completions.create(**kwargs)

        # index -> accumulating {id, name, arguments}
        acc: dict[int, dict[str, str]] = {}
        finish: str | None = None

        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if choice.finish_reason:
                finish = choice.finish_reason

            if delta and delta.content:
                yield TextDelta(text=delta.content)

            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        out["tool_calls"] = [acc[i] for i in sorted(acc)]
        out["finish"] = finish
