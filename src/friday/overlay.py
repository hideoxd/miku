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


# --------------------------------------------------------------------------- assets
def _asset_image(size: int):
    """Load the 3D Miku render (assets/miku.png), tight-cropped + width-scaled."""
    from PIL import Image

    p = Path(__file__).parent / "assets" / "miku.png"
    if not p.exists():
        return None
    try:
        im = Image.open(p).convert("RGBA")
        im = im.crop(im.getchannel("A").getbbox())
        h = int(im.height * size / im.width)
        return im.resize((size, h), Image.LANCZOS)
    except Exception:  # noqa: BLE001
        return None


def _keyed_from_rgba(img, threshold: int = 110):
    """RGBA -> RGB with transparent areas set to the colour-key (clean edges,
    no magenta fringe: kept pixels retain their original colour)."""
    from PIL import Image

    mask = img.getchannel("A").point(lambda v: 255 if v >= threshold else 0)
    out = Image.new("RGB", img.size, KEY)
    out.paste(img.convert("RGB"), (0, 0), mask)
    return out


# --------------------------------------------------------------------------- process
def _ease_out_back(t: float) -> float:
    """Overshoots past 1 then settles — a springy 'pop'."""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _scale_keyed(asset_rgba, canvas_size, scale: float):
    """Scale the RGBA asset, centre it on a canvas of `canvas_size`, colour-key it."""
    from PIL import Image

    w, h = canvas_size
    sw, sh = max(1, int(asset_rgba.width * scale)), max(1, int(asset_rgba.height * scale))
    scaled = asset_rgba.resize((sw, sh), Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(scaled, ((w - sw) // 2, (h - sh) // 2))
    return _keyed_from_rgba(canvas)


def _run_process(size: int, corner: str) -> int:
    import math
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

    # Prefer the 3D render; fall back to the drawn chibi. `POP` scales are the
    # grow-in "pop" frames; the base frame is scale 1.0 (index -1).
    POP = [0.55, 0.7, 0.82, 0.92, 1.0]
    asset = _asset_image(size)
    if asset is not None:
        img_w, img_h = asset.size
        pop_frames = [ImageTk.PhotoImage(_scale_keyed(asset, (img_w, img_h), s)) for s in POP]
        state_frames = {k: pop_frames[-1] for k in ("idle", "listening", "thinking", "speaking")}
        animate_mouth = False
    else:
        img_w = img_h = size
        drawn = {st: draw_miku(size, st) for st in ("idle", "listening", "thinking")}
        pop_frames = [ImageTk.PhotoImage(_scale_keyed(drawn["idle"], (img_w, img_h), s)) for s in POP]
        state_frames = {
            "idle": ImageTk.PhotoImage(_to_keyed(drawn["idle"])),
            "listening": ImageTk.PhotoImage(_to_keyed(drawn["listening"])),
            "thinking": ImageTk.PhotoImage(_to_keyed(drawn["thinking"])),
            "speak_open": ImageTk.PhotoImage(_to_keyed(draw_miku(size, "speaking", True))),
            "speak_closed": ImageTk.PhotoImage(_to_keyed(draw_miku(size, "speaking", False))),
        }
        animate_mouth = True

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    margin = 24
    x = margin if "left" in corner else sw - img_w - margin
    shown_y = sh - int(img_h * 0.82)  # peek: lower body clipped by the screen edge
    hidden_y = sh + 40
    root.geometry(f"{img_w}x{img_h}+{x}+{hidden_y}")

    label = tk.Label(root, bg=key_hex, bd=0, highlightthickness=0)
    label.pack()
    label.configure(image=state_frames["idle"])
    root.withdraw()
    _make_clickthrough(root)

    JUMP = 15  # ticks (~0.5s) for the jump/pop
    st = {"name": "idle", "mode": "hidden", "tick": 0, "jump": 0, "y": hidden_y}

    def tick() -> None:
        try:
            while True:
                parts = cmds.get_nowait().split()
                if not parts:
                    continue
                verb, arg = parts[0], (parts[1] if len(parts) > 1 else "")
                if verb == "show":
                    st["name"] = arg or "listening"
                    if st["mode"] in ("hidden", "hiding"):
                        st["mode"] = "jumping"
                        st["jump"] = 0
                        root.deiconify()
                        root.lift()
                elif verb == "state":
                    st["name"] = arg or st["name"]
                elif verb == "hide":
                    if st["mode"] != "hidden":
                        st["mode"] = "hiding"
                elif verb == "stop":
                    root.destroy()
                    return
        except queue.Empty:
            pass

        frame = state_frames.get(st["name"], state_frames["idle"])

        if st["mode"] == "jumping":
            st["jump"] += 1
            t = min(1.0, st["jump"] / JUMP)
            st["y"] = int(hidden_y + (shown_y - hidden_y) * _ease_out_back(t))
            # grow-in pop: pick a POP frame for the first ~60% of the jump
            pi = min(len(pop_frames) - 1, int(t / 0.6 * (len(pop_frames) - 1)))
            frame = pop_frames[pi]
            if st["jump"] >= JUMP:
                st["mode"] = "shown"
                st["y"] = shown_y
        elif st["mode"] == "shown":
            amp, freq = (7, 0.34) if st["name"] == "speaking" else (3, 0.10)
            st["y"] = shown_y + int(amp * math.sin(st["tick"] * freq))
            if animate_mouth and st["name"] == "speaking":
                frame = state_frames["speak_open"] if (st["tick"] // 6) % 2 == 0 else state_frames["speak_closed"]
        elif st["mode"] == "hiding":
            st["y"] += max(24, int((hidden_y - st["y"]) * 0.3))
            if st["y"] >= hidden_y:
                st["y"] = hidden_y
                st["mode"] = "hidden"
                root.withdraw()

        root.geometry(f"{img_w}x{img_h}+{x}+{st['y']}")
        label.configure(image=frame)
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
