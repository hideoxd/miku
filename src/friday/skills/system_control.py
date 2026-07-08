"""PC control skill — open apps/sites, control volume, media keys, type text.

Windows-focused. Actions that change the machine are kept simple and log what
they do; text typing goes to whatever window currently has focus.
"""

from __future__ import annotations

import logging
import os
import webbrowser

from .registry import SkillRegistry

log = logging.getLogger("friday.skills.system")


def _co_init() -> None:
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001
        pass


def _volume_endpoint():
    from pycaw.pycaw import AudioUtilities

    _co_init()
    device = AudioUtilities.GetSpeakers()
    # Newer pycaw: device.EndpointVolume is already the IAudioEndpointVolume.
    endpoint = getattr(device, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint
    # Older pycaw: activate the interface manually.
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def register(reg: SkillRegistry) -> None:
    @reg.register(
        name="open_application",
        description="Open/launch a Windows application by name (e.g. 'spotify', 'notepad', 'chrome').",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "App name."}},
            "required": ["name"],
            "additionalProperties": False,
        },
    )
    def open_application(name: str) -> dict:
        try:
            from AppOpener import open as app_open

            app_open(name, match_closest=True, throw_error=True, output=False)
            return {"ok": True, "opened": name}
        except Exception as exc:  # noqa: BLE001
            # Fall back to the shell (handles system apps / paths).
            try:
                os.startfile(name)  # type: ignore[attr-defined]
                return {"ok": True, "opened": name, "via": "shell"}
            except Exception:  # noqa: BLE001
                return {"ok": False, "error": f"could not open {name!r}: {exc}"}

    @reg.register(
        name="open_website",
        description="Open a URL in the default web browser.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    )
    def open_website(url: str) -> dict:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return {"ok": True, "opened": url}

    @reg.register(
        name="set_volume",
        description="Set the system output volume to a percentage (0-100).",
        parameters={
            "type": "object",
            "properties": {"percent": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["percent"],
            "additionalProperties": False,
        },
    )
    def set_volume(percent: int) -> dict:
        pct = max(0, min(int(percent), 100))
        try:
            _volume_endpoint().SetMasterVolumeLevelScalar(pct / 100.0, None)
            return {"ok": True, "volume": pct}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    @reg.register(
        name="get_volume",
        description="Get the current system output volume (percentage).",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    def get_volume() -> dict:
        try:
            scalar = _volume_endpoint().GetMasterVolumeLevelScalar()
            return {"volume": round(scalar * 100)}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    @reg.register(
        name="media_control",
        description="Send a media key: play/pause, next track, previous track, or mute.",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["playpause", "next", "previous", "mute"]}
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    )
    def media_control(action: str) -> dict:
        keymap = {
            "playpause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "mute": "volumemute",
        }
        key = keymap.get(action)
        if not key:
            return {"ok": False, "error": f"unknown action {action!r}"}
        try:
            import pyautogui

            pyautogui.press(key)
            return {"ok": True, "action": action}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    @reg.register(
        name="type_text",
        description="Type text into the currently focused window (keyboard automation).",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )
    def type_text(text: str) -> dict:
        try:
            import pyautogui

            pyautogui.write(text, interval=0.01)
            return {"ok": True, "typed_chars": len(text)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
