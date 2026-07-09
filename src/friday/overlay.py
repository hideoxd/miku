"""A little Hatsune Miku that peeks up from the screen corner.

When FRIDAY wakes ("Hi Miku"), a chibi Miku slides up from the bottom edge and
reacts to state (listening / thinking / speaking), then slides back down.

Tkinter must own its thread's main loop, and the tray already owns the main
thread — so the overlay runs as its own tiny process (``python -m friday.overlay``)
and is driven over stdin by :class:`OverlayClient`. Commands (one per line):
``show <state>`` · ``state <state>`` · ``hide`` · ``stop`` (or EOF).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("friday.overlay")

TEAL = (57, 197, 187, 255)
TEAL_D = (42, 160, 152, 255)
SKIN = (255, 235, 217, 255)
SKIN_SH = (240, 210, 190, 255)
BLUSH = (255, 170, 160, 130)
WHITE = (255, 255, 255, 255)
DARK = (60, 60, 70, 255)
RED = (220, 70, 90, 255)
KEY = (255, 0, 255)  # magenta colour-key -> transparent


# --------------------------------------------------------------------------- art
def draw_miku(size: int = 300, state: str = "idle", mouth_open: bool = False):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size // 2
    s = size / 320.0

    def S(v):
        return int(v * s)

    for sign in (-1, 1):
        x = cx + sign * S(96)
        d.rounded_rectangle([x - S(34), S(70), x + S(34), S(300)], radius=S(34), fill=TEAL)
        d.ellipse([x - S(26), S(92), x + S(26), S(128)], fill=TEAL_D)
        d.ellipse([x - S(10), S(100), x + S(10), S(120)], fill=RED)

    d.ellipse([cx - S(78), S(96), cx + S(78), S(268)], fill=SKIN)

    d.pieslice([cx - S(82), S(78), cx + S(82), S(220)], start=180, end=360, fill=TEAL)
    d.polygon([(cx - S(70), S(150)), (cx - S(40), S(150)), (cx - S(55), S(196))], fill=TEAL)
    d.polygon([(cx - S(22), S(152)), (cx + S(22), S(152)), (cx, S(200))], fill=TEAL)
    d.polygon([(cx + S(40), S(150)), (cx + S(70), S(150)), (cx + S(55), S(196))], fill=TEAL)
    d.rounded_rectangle([cx - S(84), S(150), cx - S(60), S(250)], radius=S(16), fill=TEAL)
    d.rounded_rectangle([cx + S(60), S(150), cx + S(84), S(250)], radius=S(16), fill=TEAL)

    ey = S(200)
    eo = S(26) if state == "listening" else S(24)
    for sign in (-1, 1):
        ex = cx + sign * S(34)
        d.ellipse([ex - S(22), ey - eo, ex + S(22), ey + eo], fill=WHITE, outline=DARK, width=2)
        d.ellipse([ex - S(15), ey - S(20), ex + S(15), ey + S(22)], fill=TEAL)
        d.ellipse([ex - S(8), ey - S(8), ex + S(8), ey + S(18)], fill=DARK)
        d.ellipse([ex - S(6), ey - S(16), ex + S(2), ey - S(6)], fill=WHITE)

    for sign in (-1, 1):
        bx = cx + sign * S(58)
        d.ellipse([bx - S(16), ey + S(18), bx + S(16), ey + S(36)], fill=BLUSH)

    if state == "speaking" and mouth_open:
        d.ellipse([cx - S(12), S(242), cx + S(12), S(266)], fill=(150, 60, 70, 255))
    elif state == "thinking":
        d.line([cx - S(10), S(252), cx + S(10), S(252)], fill=DARK, width=S(3))
    else:
        d.arc([cx - S(14), S(236), cx + S(14), S(262)], start=20, end=160, fill=DARK, width=S(3))

    for sign in (-1, 1):
        hx = cx + sign * S(52)
        d.rounded_rectangle([hx - S(26), size - S(40), hx + S(26), size + S(10)],
                            radius=S(16), fill=SKIN)
        for i in range(4):
            fx = hx - S(20) + i * S(13)
            d.rounded_rectangle([fx, size - S(44), fx + S(10), size - S(20)],
                                radius=S(5), fill=SKIN_SH)
    return img


def _to_keyed(img):
    from PIL import Image

    bg = Image.new("RGBA", img.size, KEY + (255,))
    bg.alpha_composite(img)
    mask = img.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    return Image.composite(bg.convert("RGB"), Image.new("RGB", img.size, KEY), mask)


# --------------------------------------------------------------------------- client
def _python_exe() -> str:
    p = Path(sys.executable)
    if p.name.lower() == "pythonw.exe":
        cand = p.with_name("python.exe")
        if cand.exists():
            return str(cand)
    return str(p)


class OverlayClient:
    """Spawns the overlay process and drives it over stdin."""

    def __init__(self, size: int = 240, corner: str = "bottom-right") -> None:
        self._proc: subprocess.Popen | None = None
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._proc = subprocess.Popen(
                [_python_exe(), "-m", "friday.overlay", "--size", str(size), "--corner", corner],
                stdin=subprocess.PIPE,
                cwd=str(Path(__file__).resolve().parents[2]),
                creationflags=flags,
                text=True,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("could not start overlay: %s", exc)
            self._proc = None

    def _send(self, line: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError):
            self._proc = None  # pipe died

    def show(self, state: str = "listening") -> None:
        self._send(f"show {state}")

    def set_state(self, state: str) -> None:
        self._send(f"state {state}")

    def hide(self) -> None:
        self._send("hide")

    def stop(self) -> None:
        self._send("stop")
        if self._proc is not None:
            try:
                self._proc.stdin.close()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            try:
                self._proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                self._proc.terminate()


# --------------------------------------------------------------------------- process
def _run_process(size: int, corner: str) -> int:
    import queue
    import tkinter as tk

    from PIL import ImageTk

    cmds: "queue.Queue[str]" = queue.Queue()

    def reader() -> None:
        try:
            for line in sys.stdin:
                cmds.put(line.strip())
        except Exception:  # noqa: BLE001
            pass
        cmds.put("stop")

    threading.Thread(target=reader, daemon=True).start()

    key_hex = "#%02x%02x%02x" % KEY
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-transparentcolor", key_hex)
    except tk.TclError:
        pass
    root.configure(bg=key_hex)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    margin = 30
    x = margin if "left" in corner else sw - size - margin
    shown_y = sh - size + 30
    hidden_y = sh + 20
    cur = {"y": hidden_y}
    root.geometry(f"{size}x{size}+{x}+{hidden_y}")

    frames = {
        "idle": ImageTk.PhotoImage(_to_keyed(draw_miku(size, "idle"))),
        "listening": ImageTk.PhotoImage(_to_keyed(draw_miku(size, "listening"))),
        "thinking": ImageTk.PhotoImage(_to_keyed(draw_miku(size, "thinking"))),
        "speak_open": ImageTk.PhotoImage(_to_keyed(draw_miku(size, "speaking", True))),
        "speak_closed": ImageTk.PhotoImage(_to_keyed(draw_miku(size, "speaking", False))),
    }
    label = tk.Label(root, bg=key_hex, bd=0, highlightthickness=0)
    label.pack()
    label.configure(image=frames["idle"])
    root.withdraw()
    _make_clickthrough(root)

    st = {"name": "idle", "visible": False, "tick": 0}

    def tick() -> None:
        try:
            while True:
                parts = cmds.get_nowait().split()
                if not parts:
                    continue
                verb = parts[0]
                arg = parts[1] if len(parts) > 1 else ""
                if verb == "show":
                    st["name"] = arg or "listening"
                    st["visible"] = True
                    root.deiconify()
                    root.lift()
                elif verb == "state":
                    st["name"] = arg or st["name"]
                elif verb == "hide":
                    st["visible"] = False
                elif verb == "stop":
                    root.destroy()
                    return
        except queue.Empty:
            pass

        target = shown_y if st["visible"] else hidden_y
        if cur["y"] != target:
            step = max(9, int(abs(target - cur["y"]) * 0.25))
            cur["y"] += step if target > cur["y"] else -step
            if abs(cur["y"] - target) < step:
                cur["y"] = target
            root.geometry(f"{size}x{size}+{x}+{cur['y']}")
            if not st["visible"] and cur["y"] == hidden_y:
                root.withdraw()

        name = st["name"]
        if name == "speaking":
            img = frames["speak_open"] if (st["tick"] // 6) % 2 == 0 else frames["speak_closed"]
        else:
            img = frames.get(name, frames["idle"])
        label.configure(image=img)
        st["tick"] += 1
        root.after(33, tick)

    root.after(33, tick)
    root.mainloop()
    return 0


def _make_clickthrough(root) -> None:
    try:
        import win32con
        import win32gui

        root.update_idletasks()
        hwnd = win32gui.GetParent(root.winfo_id()) or root.winfo_id()
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(
            hwnd, win32con.GWL_EXSTYLE,
            ex | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW,
        )
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=240)
    ap.add_argument("--corner", default="bottom-right")
    args = ap.parse_args()
    return _run_process(args.size, args.corner)


if __name__ == "__main__":
    sys.exit(main())
