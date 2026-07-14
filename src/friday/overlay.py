"""The Miku desktop mascot, and the client that drives her.

Two backends, same one-line command protocol (``show <state>`` ·
``state <state>`` · ``hide`` · ``stop``):

* ``3d`` (default) — the real-time animated 3D Miku in ``mascot3d/`` (Electron +
  three-vrm: articulated head/arms/torso, cursor gaze, draggable, headpat).
  Driven over a localhost TCP socket (Electron's stdin is unreliable on
  Windows); the socket doubles as a parent-death signal.
* ``png`` (fallback) — this module's Tkinter window showing the static rendered
  PNG (or the drawn chibi if the asset is missing), driven over stdin. Tkinter
  must own its thread's main loop and the tray already owns the main thread, so
  it runs as its own process (``python -m friday.overlay``).

:class:`OverlayClient` picks the backend, spawns the process, restarts it if it
dies (budgeted), and restores the visible state after a restart.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("friday.overlay")

ROOT = Path(__file__).resolve().parents[2]
MASCOT3D_DIR = ROOT / "mascot3d"
ELECTRON_EXE = MASCOT3D_DIR / "node_modules" / "electron" / "dist" / "electron.exe"
MASCOT_BUNDLE = MASCOT3D_DIR / "renderer" / "dist" / "bundle.js"
VRM_PATH = ROOT / "models" / "miku.vrm"

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
    """Spawns the mascot process (3D or PNG backend) and drives it.

    Resilient by design: if the child dies (crash, Task-Manager kill), the next
    command restarts it — at most ``_RESTART_BUDGET`` times per
    ``_RESTART_WINDOW`` seconds so a crash-looping mascot can't spam — and
    re-shows the last visible state so Miku comes back where she was.
    """

    _RESTART_BUDGET = 3
    _RESTART_WINDOW = 300.0  # seconds

    def __init__(self, settings=None, *, size: int = 240, corner: str = "bottom-right") -> None:
        if settings is not None:
            self._size = settings.overlay_size
            self._corner = settings.overlay_corner
            self._fps = getattr(settings, "overlay_fps", 30)
            requested = getattr(settings, "overlay_backend", "3d")
        else:  # back-compat with the old (size=, corner=) construction
            self._size, self._corner, self._fps, requested = size, corner, 30, "3d"

        self.backend = self._resolve_backend(requested)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._pending: list[str] = []  # 3d: lines queued until the socket connects
        self._last: str | None = None  # last visible state (None = hidden)
        self._restarts: list[float] = []
        self._stopped = False
        if self.backend != "off":
            with self._lock:
                self._spawn_locked()

    # -- backend selection --------------------------------------------------

    @staticmethod
    def _resolve_backend(requested: str) -> str:
        requested = (requested or "3d").lower()
        if requested == "off":
            return "off"
        if requested == "3d":
            missing = [p for p in (ELECTRON_EXE, MASCOT_BUNDLE, VRM_PATH) if not p.exists()]
            if not missing:
                return "3d"
            log.warning(
                "3D mascot unavailable (missing: %s) — using the PNG overlay. "
                "Setup: `cd mascot3d && npm install` and `python scripts/fetch_miku_vrm.py`",
                ", ".join(str(p.relative_to(ROOT)) for p in missing),
            )
        return "png"

    # -- process / transport ------------------------------------------------

    def _spawn_locked(self) -> bool:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            if self.backend == "3d":
                srv = socket.socket()
                srv.bind(("127.0.0.1", 0))
                srv.listen(1)
                port = srv.getsockname()[1]
                (ROOT / "cache").mkdir(exist_ok=True)
                self._proc = subprocess.Popen(
                    [
                        str(ELECTRON_EXE),
                        str(MASCOT3D_DIR),
                        "--ctl-port", str(port),
                        "--size", str(self._size),
                        "--corner", self._corner,
                        "--fps", str(self._fps),
                        "--model", str(VRM_PATH),
                        "--state-file", str(ROOT / "cache" / "mascot_window.json"),
                    ],
                    creationflags=flags,
                )
                self._sock = None
                threading.Thread(
                    target=self._accept, args=(srv, self._proc), daemon=True, name="mascot-accept"
                ).start()
            else:
                self._proc = subprocess.Popen(
                    [
                        _python_exe(), "-m", "friday.overlay",
                        "--size", str(self._size), "--corner", self._corner,
                    ],
                    stdin=subprocess.PIPE,
                    cwd=str(ROOT),
                    creationflags=flags,
                    text=True,
                )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("could not start overlay: %s", exc)
            self._proc = None
            return False

    def _accept(self, srv: socket.socket, proc: subprocess.Popen) -> None:
        """Wait (off-thread) for the Electron child to connect back, then flush
        any commands that arrived while it was booting."""
        conn: socket.socket | None = None
        try:
            srv.settimeout(30)
            conn, _ = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("3D mascot never connected: %s", exc)
        finally:
            srv.close()
        with self._lock:
            if self._proc is not proc:  # a restart superseded us
                if conn is not None:
                    conn.close()
                return
            self._sock = conn
            if conn is not None:
                for line in self._pending:
                    self._write_locked(line)
            self._pending.clear()

    def _alive_locked(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _write_locked(self, line: str) -> bool:
        """Push one command to the child; True on (apparent) success."""
        if self.backend == "3d":
            if self._sock is None:
                if self._alive_locked():
                    self._pending.append(line)  # still booting
                    return True
                return False
            try:
                self._sock.sendall((line + "\n").encode("utf-8"))
                return True
            except OSError:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
                return False
        # png backend: stdin pipe
        if self._proc is None or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _restart_locked(self) -> bool:
        now = time.monotonic()
        self._restarts = [t for t in self._restarts if now - t < self._RESTART_WINDOW]
        if len(self._restarts) >= self._RESTART_BUDGET:
            return False  # crash-looping — give up quietly, voice keeps working
        self._restarts.append(now)
        log.info("mascot process died — restarting")
        if self._proc is not None:
            try:
                self._proc.kill()
            except OSError:
                pass
        self._sock = None
        self._pending.clear()
        if not self._spawn_locked():
            return False
        if self._last is not None:
            self._write_locked(f"show {self._last}")  # come back where she was
        return True

    def _send(self, line: str) -> None:
        with self._lock:
            if self._stopped or self.backend == "off":
                return
            if not self._alive_locked():
                if not self._restart_locked():
                    return
            if not self._write_locked(line):
                if self._restart_locked():
                    self._write_locked(line)

    # -- public API -----------------------------------------------------------

    def show(self, state: str = "listening") -> None:
        self._last = state
        self._send(f"show {state}")

    def set_state(self, state: str) -> None:
        self._last = state
        self._send(f"state {state}")

    def emote(self, name: str = "nod") -> None:
        """Play a one-shot reaction (nod/giggle/stretch/…) without changing state.

        A no-op on the PNG backend, which has no emote vocabulary — unknown
        verbs are simply ignored there.
        """
        self._send(f"emote {name}")

    def hide(self) -> None:
        self._last = None
        self._send("hide")

    def stop(self) -> None:
        self._send("stop")
        with self._lock:
            self._stopped = True
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            if self._proc is not None:
                if self._proc.stdin is not None:
                    try:
                        self._proc.stdin.close()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    self._proc.wait(timeout=3)
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
