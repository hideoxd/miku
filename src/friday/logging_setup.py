"""Structured, timestamped logging to console + a rotating file.

Also exposes a tiny ``StageTimer`` used as the latency dashboard the plan calls
for (wake -> stt -> first-token -> first-audio).
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import ROOT

_configured = False


def setup_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return

    logs_dir = ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Under pythonw (tray/background) there is no console — sys.stderr is None,
    # so only attach a stream handler when one actually exists.
    import sys

    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

    fileh = RotatingFileHandler(
        logs_dir / "friday.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fileh.setFormatter(fmt)
    root.addHandler(fileh)

    # Quiet noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    _configured = True


@contextmanager
def stage_timer(name: str, log: logging.Logger | None = None):
    """Log how long a pipeline stage took, for the latency dashboard."""
    log = log or logging.getLogger("friday.timing")
    start = time.perf_counter()
    try:
        yield
    finally:
        dt = (time.perf_counter() - start) * 1000
        log.info("⏱  %-18s %6.0f ms", name, dt)
