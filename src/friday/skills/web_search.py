"""Web search skill — keyless, via DuckDuckGo (ddgs)."""

from __future__ import annotations

import logging

from .registry import SkillRegistry

log = logging.getLogger("friday.skills.web")


def register(reg: SkillRegistry) -> None:
    @reg.register(
        name="web_search",
        description=(
            "Search the web for current information (news, facts, weather, prices, "
            "anything you don't know). Returns a few top results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 8,
                    "description": "How many results (default 5).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )
    def web_search(query: str, max_results: int = 5) -> dict:
        try:
            from ddgs import DDGS
        except ImportError:
            return {"error": "web search unavailable (pip install ddgs)"}

        max_results = max(1, min(int(max_results), 8))
        try:
            with DDGS() as ddgs:
                hits = list(ddgs.text(query, max_results=max_results))
        except Exception as exc:  # noqa: BLE001
            log.warning("web search failed: %s", exc)
            return {"error": f"search failed: {exc}"}

        results = [
            {
                "title": h.get("title", ""),
                "snippet": h.get("body", ""),
                "url": h.get("href", ""),
            }
            for h in hits
        ]
        return {"query": query, "results": results}
