"""Timers & reminders — a background threading.Timer that fires a callback.

In Phase 0 the callback just logs/prints; later phases can route the alert
through the TTS pipeline so Miku announces it out loud.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from .registry import SkillRegistry

log = logging.getLogger("friday.skills.timers")

# name -> Timer, so we can list/cancel them.
_active: dict[str, threading.Timer] = {}
_lock = threading.Lock()


def register(reg: SkillRegistry, on_fire: Callable[[str], None] | None = None) -> None:
    """Register timer skills. ``on_fire(message)`` is invoked when a timer ends."""

    def _fire(label: str, seconds: int) -> None:
        with _lock:
            _active.pop(label, None)
        msg = f"Timer '{label}' ({seconds}s) finished."
        log.info("🔔 %s", msg)
        if on_fire:
            on_fire(msg)

    @reg.register(
        name="set_timer",
        description="Start a countdown timer that alerts when it finishes.",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "minimum": 1, "description": "Duration in seconds."},
                "label": {"type": "string", "description": "Short name for the timer, e.g. 'tea'."},
            },
            "required": ["seconds"],
            "additionalProperties": False,
        },
    )
    def set_timer(seconds: int, label: str = "timer") -> dict[str, object]:
        with _lock:
            if label in _active:
                _active[label].cancel()
            t = threading.Timer(seconds, _fire, args=(label, seconds))
            t.daemon = True
            _active[label] = t
            t.start()
        return {"ok": True, "label": label, "seconds": seconds}

    @reg.register(
        name="list_timers",
        description="List the labels of all currently running timers.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    def list_timers() -> dict[str, object]:
        with _lock:
            return {"active": sorted(_active.keys())}

    @reg.register(
        name="cancel_timer",
        description="Cancel a running timer by its label.",
        parameters={
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": ["label"],
            "additionalProperties": False,
        },
    )
    def cancel_timer(label: str) -> dict[str, object]:
        with _lock:
            t = _active.pop(label, None)
        if t is None:
            return {"ok": False, "reason": f"no timer named '{label}'"}
        t.cancel()
        return {"ok": True, "cancelled": label}
