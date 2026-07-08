"""Windows auto-start management for the FRIDAY tray app.

Installs a tiny .vbs launcher into the user's Startup folder that runs
``pythonw -m friday.tray`` fully hidden (no console window) at every logon.
No admin rights needed, and it's trivially reversible.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .config import ROOT

log = logging.getLogger("friday.autostart")

_VBS_NAME = "FRIDAY.vbs"


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _vbs_path() -> Path:
    return _startup_dir() / _VBS_NAME


def _pythonw() -> Path:
    """The windowed (no-console) interpreter next to the current one."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def _vbs_contents() -> str:
    pyw = str(_pythonw())
    cwd = str(ROOT)
    # windowStyle 0 = hidden, bWaitOnReturn = False.
    return (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.CurrentDirectory = "{cwd}"\r\n'
        f'sh.Run """{pyw}"" -m friday.tray", 0, False\r\n'
    )


def install() -> Path:
    startup = _startup_dir()
    startup.mkdir(parents=True, exist_ok=True)
    path = _vbs_path()
    path.write_text(_vbs_contents(), encoding="utf-8")
    log.info("installed auto-start: %s", path)
    return path


def uninstall() -> bool:
    path = _vbs_path()
    if path.exists():
        path.unlink()
        log.info("removed auto-start: %s", path)
        return True
    return False


def is_installed() -> bool:
    return _vbs_path().exists()


def status() -> dict:
    return {
        "installed": is_installed(),
        "launcher": str(_vbs_path()),
        "pythonw": str(_pythonw()),
        "cwd": str(ROOT),
    }
