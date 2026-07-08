"""Trivial always-available skills (no external deps). Phase 0 proof tools."""

from __future__ import annotations

from datetime import datetime

from .registry import SkillRegistry


def register(reg: SkillRegistry) -> None:
    @reg.register(
        name="get_current_datetime",
        description="Get the current local date and time. Use for any 'what time/day is it' question.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    def get_current_datetime() -> dict[str, str]:
        now = datetime.now().astimezone()
        return {
            "iso": now.isoformat(timespec="seconds"),
            "spoken": now.strftime("%A, %d %B %Y, %I:%M %p"),
            "timezone": str(now.tzinfo),
        }
