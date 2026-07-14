"""FRIDAY system-tray app — runs the assistant hidden in the background.

Launch (hidden, via pythonw): ``pythonw -m friday.tray``
The tray icon colour reflects state; the menu lets you pause listening, open
logs, restart, toggle auto-start, and quit. Single-instance guarded.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from . import autostart
from .config import ROOT, get_settings
from .logging_setup import setup_logging
from .service import VoiceService

log = logging.getLogger("friday.tray")

# state -> icon colour
_COLORS = {
    "loading": (120, 120, 120),
    "idle": (57, 197, 187),      # Miku teal
    "listening": (76, 175, 80),  # green
    "thinking": (255, 179, 0),   # amber
    "speaking": (33, 150, 243),  # blue
    "paused": (158, 158, 158),   # grey
    "error": (229, 57, 53),      # red
    "stopped": (96, 125, 139),
}

# Keep the single-instance mutex handle alive for the process lifetime.
_MUTEX = None


def _already_running() -> bool:
    global _MUTEX
    try:
        import win32api
        import win32event
        import winerror

        _MUTEX = win32event.CreateMutex(None, False, "Global\\FRIDAY_TRAY_SINGLETON")
        return win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001 — if pywin32 missing, don't block startup
        return False


def _release_mutex() -> None:
    # Close the single-instance mutex handle so its named object is destroyed
    # immediately, instead of lingering until this process fully exits. Needed
    # by restart() so the replacement instance can claim singleton ownership
    # while this one is still tearing down (which can take a few seconds).
    global _MUTEX
    if _MUTEX is None:
        return
    try:
        import win32api

        win32api.CloseHandle(_MUTEX)
    except Exception:  # noqa: BLE001
        pass
    _MUTEX = None


def _show_error(msg: str) -> None:
    # Under pythonw there is no console/stderr, so a message box is the only
    # way to make a fatal startup failure visible instead of silent.
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, "FRIDAY", 0x10)  # MB_ICONERROR
    except Exception:  # noqa: BLE001
        pass


def _make_icon(color):
    from PIL import Image, ImageDraw, ImageFont

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 4, size - 4), fill=color)
    try:
        font = ImageFont.truetype("arialbd.ttf", 40)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    # centred "F"
    try:
        box = d.textbbox((0, 0), "F", font=font)
        w, h = box[2] - box[0], box[3] - box[1]
        d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), "F", fill="white", font=font)
    except Exception:  # noqa: BLE001
        d.text((22, 12), "F", fill="white")
    return img


def main() -> int:
    if _already_running():
        # Another tray instance owns the assistant; exit quietly.
        return 0

    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 — a bad .env value must not kill us silently
        # Logging isn't configured yet; bring up file logging at the default
        # level so the error is captured, then surface it — under pythonw the
        # exception would otherwise propagate with no console and no feedback.
        setup_logging()
        log.exception("failed to load settings — check .env for invalid values")
        _show_error(
            "FRIDAY could not start: a value in your .env is invalid.\n"
            "See logs\\friday.log for details."
        )
        return 1

    setup_logging(settings.log_level)
    log.info("FRIDAY tray starting")

    import pystray
    from pystray import Menu, MenuItem

    icon = pystray.Icon("friday", _make_icon(_COLORS["loading"]), "FRIDAY — starting")

    def on_state(state: str) -> None:
        try:
            icon.icon = _make_icon(_COLORS.get(state, _COLORS["idle"]))
            icon.title = f"FRIDAY — {state}"
        except Exception:  # noqa: BLE001
            pass

    def on_event(kind: str, msg: str) -> None:
        if not settings.tray_notifications:
            return
        try:
            icon.notify(msg, "FRIDAY")
        except Exception:  # noqa: BLE001
            pass

    service = VoiceService(settings, verbose=False, on_state=on_state, on_event=on_event)

    # -- menu actions --
    def toggle_pause(_icon, _item) -> None:
        service.resume() if service.is_paused else service.pause()

    def open_logs(_icon, _item) -> None:
        try:
            os.startfile(str(ROOT / "logs"))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            log.exception("could not open logs")

    def toggle_autostart(_icon, _item) -> None:
        try:
            autostart.uninstall() if autostart.is_installed() else autostart.install()
        except Exception:  # noqa: BLE001
            log.exception("autostart toggle failed")

    def restart(_icon, _item) -> None:
        # Relaunch a fresh hidden instance, then quit this one. Release the
        # single-instance mutex first so the replacement can claim singleton
        # ownership even while this process is still tearing down; otherwise it
        # sees ERROR_ALREADY_EXISTS and exits, leaving no tray running.
        _release_mutex()
        try:
            pyw = str(__import__("pathlib").Path(sys.executable).with_name("pythonw.exe"))
            subprocess.Popen([pyw, "-m", "friday.tray"], cwd=str(ROOT))
        except Exception:  # noqa: BLE001
            log.exception("restart failed")
        quit_app(_icon, _item)

    def quit_app(_icon, _item) -> None:
        log.info("FRIDAY tray quitting")
        service.stop()
        icon.stop()

    icon.menu = Menu(
        MenuItem(lambda item: f"FRIDAY — {service.state}", None, enabled=False),
        Menu.SEPARATOR,
        MenuItem(
            lambda item: "Resume listening" if service.is_paused else "Pause listening",
            toggle_pause,
        ),
        MenuItem("Open logs", open_logs),
        MenuItem("Restart", restart),
        MenuItem("Start at login", toggle_autostart, checked=lambda item: autostart.is_installed()),
        Menu.SEPARATOR,
        MenuItem("Quit", quit_app),
    )

    service.start()
    icon.run()  # blocks on the Windows message loop until icon.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
