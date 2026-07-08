"""Skill registry assembly.

``build_default_registry`` wires up the skills available in the current phase.
Later phases add ``system_control``, ``web_search`` and ``productivity`` here.
"""

from __future__ import annotations

from typing import Callable

from . import basic, timers
from .registry import SkillRegistry

__all__ = ["SkillRegistry", "build_default_registry"]


def build_default_registry(on_timer_fire: Callable[[str], None] | None = None) -> SkillRegistry:
    reg = SkillRegistry()
    basic.register(reg)
    timers.register(reg, on_fire=on_timer_fire)
    return reg
