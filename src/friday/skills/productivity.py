"""Productivity skill — Todoist tasks via the REST API.

Enabled when FRIDAY_TODOIST_TOKEN is set (get it from Todoist → Settings →
Integrations → Developer → API token).
"""

from __future__ import annotations

import logging

from .registry import SkillRegistry

log = logging.getLogger("friday.skills.todoist")

_API = "https://api.todoist.com/rest/v2"


def register(reg: SkillRegistry, token: str) -> None:
    if not token:
        return  # skill unavailable without a token

    def _headers() -> dict:
        return {"Authorization": f"Bearer {token}"}

    @reg.register(
        name="list_tasks",
        description="List the user's active Todoist tasks (optionally filtered, e.g. 'today').",
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Optional Todoist filter, e.g. 'today', 'overdue', '#Work'.",
                }
            },
            "additionalProperties": False,
        },
    )
    def list_tasks(filter: str | None = None) -> dict:
        import requests

        params = {"filter": filter} if filter else {}
        try:
            r = requests.get(f"{_API}/tasks", headers=_headers(), params=params, timeout=15)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Todoist error: {exc}"}
        tasks = [
            {"id": t["id"], "content": t["content"], "due": (t.get("due") or {}).get("string")}
            for t in r.json()
        ]
        return {"count": len(tasks), "tasks": tasks[:25]}

    @reg.register(
        name="add_task",
        description="Add a task to Todoist, with an optional natural-language due date.",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The task text."},
                "due_string": {
                    "type": "string",
                    "description": "Natural due date, e.g. 'tomorrow at 5pm', 'every Monday'.",
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    )
    def add_task(content: str, due_string: str | None = None) -> dict:
        import requests

        payload: dict = {"content": content}
        if due_string:
            payload["due_string"] = due_string
        try:
            r = requests.post(f"{_API}/tasks", headers=_headers(), json=payload, timeout=15)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Todoist error: {exc}"}
        t = r.json()
        return {"ok": True, "id": t["id"], "content": t["content"]}

    @reg.register(
        name="complete_task",
        description="Mark a Todoist task complete by its id (get ids from list_tasks first).",
        parameters={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    )
    def complete_task(task_id: str) -> dict:
        import requests

        try:
            r = requests.post(f"{_API}/tasks/{task_id}/close", headers=_headers(), timeout=15)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Todoist error: {exc}"}
        return {"ok": True, "completed": task_id}
