"""Skill registry assembly.

``build_default_registry`` wires up every available skill: always-on basics +
timers, plus the Phase-4 skills (PC control, web search, Todoist, and Google
Calendar/Gmail) gated on config / available credentials.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..config import Settings, get_settings
from . import basic, timers
from .registry import SkillRegistry

log = logging.getLogger("friday.skills")

__all__ = ["SkillRegistry", "build_default_registry"]


def build_default_registry(
    on_timer_fire: Callable[[str], None] | None = None,
    settings: Settings | None = None,
) -> SkillRegistry:
    settings = settings or get_settings()
    reg = SkillRegistry()

    # Always-on
    basic.register(reg)
    timers.register(reg, on_fire=on_timer_fire)

    # Phase 4 skills
    if settings.enable_web_search:
        from . import web_search

        web_search.register(reg)

    if settings.enable_pc_control:
        try:
            from . import system_control

            system_control.register(reg)
        except Exception as exc:  # noqa: BLE001
            log.warning("PC control skills unavailable: %s", exc)

    if settings.todoist_token:
        from . import productivity

        productivity.register(reg, settings.todoist_token)

    try:
        from . import google_apis

        if google_apis.available():
            google_apis.register(reg)
            log.info("Google Calendar/Gmail skills enabled")
    except Exception as exc:  # noqa: BLE001
        log.warning("Google skills unavailable: %s", exc)

    log.info("skills registered: %s", [t["function"]["name"] for t in reg.tools_schema()])
    return reg
