"""Google Calendar + Gmail skills (optional).

Activates only when a Google OAuth client file (``credentials.json``) is present
in the repo root. On first use it opens a browser for consent and caches
``token.json``. Set up: create an OAuth "Desktop app" client in Google Cloud
Console, enable the Calendar + Gmail APIs, download credentials.json here.

Destructive/outward actions (send_email) are gated behind an explicit ``confirm``.
"""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from pathlib import Path

from ..config import ROOT
from .registry import SkillRegistry

log = logging.getLogger("friday.skills.google")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
_CREDS = ROOT / "credentials.json"
_TOKEN = ROOT / "token.json"


def available() -> bool:
    return _CREDS.exists()


def _service(api: str, version: str):
    """Build an authorized Google API client from a cached token.

    Never runs the interactive consent flow here: this is called from a skill
    handler on the single voice-service thread, and ``run_local_server`` would
    block that thread (freezing wake word / barge-in / stop) until the user
    finished browser consent. If no usable token exists, raise a clear error so
    the model relays it — run ``authorize()`` (see ``__main__``) to set up.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = None
    if _TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _TOKEN.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Google authorization needed — run "
                "'python -m friday.skills.google_apis' once to grant access."
            )
    return build(api, version, credentials=creds, cache_discovery=False)


def authorize() -> None:
    """Run the interactive OAuth consent flow and cache ``token.json``.

    Setup-only: opens a browser and blocks until consent, so it must NOT run on
    the voice-service thread. Invoke it as a one-off from a terminal.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS), SCOPES)
    creds = flow.run_local_server(port=0)
    _TOKEN.write_text(creds.to_json(), encoding="utf-8")


def register(reg: SkillRegistry) -> None:
    if not available():
        return

    @reg.register(
        name="list_calendar_events",
        description="List upcoming Google Calendar events.",
        parameters={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "additionalProperties": False,
        },
    )
    def list_calendar_events(max_results: int = 10) -> dict:
        from datetime import datetime, timezone

        try:
            svc = _service("calendar", "v3")
            now = datetime.now(timezone.utc).isoformat()
            res = (
                svc.events()
                .list(
                    calendarId="primary",
                    timeMin=now,
                    maxResults=max(1, min(int(max_results), 20)),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Calendar error: {exc}"}
        events = [
            {
                "summary": e.get("summary", "(no title)"),
                "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
            }
            for e in res.get("items", [])
        ]
        return {"count": len(events), "events": events}

    @reg.register(
        name="create_calendar_event",
        description="Create a Google Calendar event. Times are RFC3339, e.g. 2026-07-10T15:00:00.",
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start": {"type": "string", "description": "Start datetime (RFC3339)."},
                "end": {"type": "string", "description": "End datetime (RFC3339)."},
                "description": {"type": "string"},
            },
            "required": ["summary", "start", "end"],
            "additionalProperties": False,
        },
    )
    def create_calendar_event(summary: str, start: str, end: str, description: str = "") -> dict:
        try:
            svc = _service("calendar", "v3")
            body = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start},
                "end": {"dateTime": end},
            }
            ev = svc.events().insert(calendarId="primary", body=body).execute()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Calendar error: {exc}"}
        return {"ok": True, "id": ev.get("id"), "link": ev.get("htmlLink")}

    @reg.register(
        name="list_recent_emails",
        description="List recent Gmail messages (subjects + senders).",
        parameters={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "minimum": 1, "maximum": 15},
                "unread_only": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    )
    def list_recent_emails(max_results: int = 8, unread_only: bool = False) -> dict:
        try:
            svc = _service("gmail", "v1")
            q = "is:unread" if unread_only else None
            listing = (
                svc.users()
                .messages()
                .list(userId="me", maxResults=max(1, min(int(max_results), 15)), q=q)
                .execute()
            )
            out = []
            for m in listing.get("messages", []):
                msg = (
                    svc.users()
                    .messages()
                    .get(userId="me", id=m["id"], format="metadata",
                         metadataHeaders=["From", "Subject"])
                    .execute()
                )
                hdrs = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                out.append({"from": hdrs.get("From", ""), "subject": hdrs.get("Subject", "")})
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Gmail error: {exc}"}
        return {"count": len(out), "emails": out}

    @reg.register(
        name="send_email",
        description=(
            "Send an email via Gmail. This is irreversible — only call with confirm=true "
            "AFTER the user has verbally confirmed the recipient, subject and body."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "confirm": {"type": "boolean", "description": "Must be true to actually send."},
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
        requires_confirmation=True,
    )
    def send_email(to: str, subject: str, body: str, confirm: bool = False) -> dict:
        if not confirm:
            return {
                "needs_confirmation": True,
                "message": f"About to email {to} — subject '{subject}'. "
                "Confirm with the user, then call again with confirm=true.",
            }
        try:
            svc = _service("gmail", "v1")
            mime = MIMEText(body)
            mime["to"] = to
            mime["subject"] = subject
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
            svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Gmail error: {exc}"}
        return {"ok": True, "sent_to": to}


if __name__ == "__main__":  # one-off setup: grant Google access, cache token.json
    authorize()
