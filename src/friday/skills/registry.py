"""A tiny function-calling registry.

Skills register a Python handler + its JSON schema; the LLM engine gets the
schemas via :meth:`SkillRegistry.tools_schema` and dispatches calls via
:meth:`SkillRegistry.dispatch`. Handlers return a JSON-serialisable result (or
a plain string) that is fed back to the model as the tool result.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("friday.skills")

Handler = Callable[..., Any]


@dataclass
class Skill:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments
    handler: Handler
    requires_confirmation: bool = False  # hard-to-reverse actions (Phase 4)


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        *,
        requires_confirmation: bool = False,
    ) -> Callable[[Handler], Handler]:
        """Decorator to register a skill handler."""

        def deco(fn: Handler) -> Handler:
            if name in self._skills:
                raise ValueError(f"skill already registered: {name}")
            self._skills[name] = Skill(
                name=name,
                description=description,
                parameters=parameters,
                handler=fn,
                requires_confirmation=requires_confirmation,
            )
            log.debug("registered skill: %s", name)
            return fn

        return deco

    def tools_schema(self) -> list[dict[str, Any]]:
        """OpenAI-style tool schemas for every registered skill."""
        return [
            {
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.parameters,
                },
            }
            for s in self._skills.values()
        ]

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def dispatch(self, name: str, arguments: str | dict[str, Any]) -> str:
        """Run a skill by name; always returns a string for the model.

        Never raises: tool errors are returned as an ``error`` payload so the
        model can recover instead of the whole turn crashing.
        """
        skill = self._skills.get(name)
        if skill is None:
            return json.dumps({"error": f"unknown tool: {name}"})

        try:
            args = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"bad JSON arguments: {exc}"})

        # Drop args the handler doesn't accept, so a hallucinated extra field
        # doesn't blow up the call.
        sig = inspect.signature(skill.handler)
        if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            args = {k: v for k, v in args.items() if k in sig.parameters}

        try:
            result = skill.handler(**args)
        except Exception as exc:  # noqa: BLE001 — surface to the model, don't crash
            log.exception("skill %s failed", name)
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

        if isinstance(result, str):
            return result
        try:
            return json.dumps(result)
        except (TypeError, ValueError):
            return str(result)
