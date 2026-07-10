// FRIDAY 3D mascot — Electron main process.
//
// Owns the transparent always-on-top window and everything OS-level: the
// command bridge from the Python service (`show <state>` / `state <state>` /
// `hide` / `stop`, one line each, over a localhost TCP socket — Electron's
// process.stdin closes spuriously on Windows, so stdin is only a dev fallback),
// cursor polling for gaze + drag, per-pixel click-through toggling requested by
// the renderer, and window-position persistence. Animation lives in the renderer.
//
// Flags: --ctl-port N (control socket the Python parent listens on)
//        --size N --corner bottom-right --fps N --model <path.vrm>
//        --state-file <path.json> --dev (opaque window + devtools)
//        --screenshot <out.png> (show, wait, capture, quit — for testing)
//        --shot-state <state> (state to pose for --screenshot)

const { app, BrowserWindow, screen, ipcMain } = require("electron");
const fs = require("fs");
const net = require("net");
const path = require("path");
const readline = require("readline");

function argVal(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}
const hasFlag = (n) => process.argv.includes("--" + n);

const SIZE = parseInt(argVal("size", "240"), 10);
const FPS = Math.max(10, Math.min(60, parseInt(argVal("fps", "30"), 10)));
const CORNER = argVal("corner", "bottom-right");
const MODEL = path.resolve(argVal("model", path.join(__dirname, "..", "models", "miku.vrm")));
const STATE_FILE = path.resolve(argVal("state-file", path.join(__dirname, "window-state.json")));
const DEBUG = hasFlag("dev"); // NB: "--debug" is reserved by Electron itself
const SCREENSHOT = argVal("screenshot", null);
const CTL_PORT = parseInt(argVal("ctl-port", "0"), 10);

const W = SIZE + 80;
const H = Math.round(SIZE * 1.8);

let win = null;
let ready = false; // renderer finished loading the model
const pending = []; // commands received before the renderer was ready
let dragOffset = null; // {dx, dy} while the user is dragging the mascot
let hideFallback = null;

function defaultPosition() {
  const wa = screen.getPrimaryDisplay().workArea;
  const margin = 24;
  const x = CORNER.includes("left") ? wa.x + margin : wa.x + wa.width - W - margin;
  const y = wa.y + wa.height - H; // feet on the taskbar edge
  return { x, y };
}

function loadPosition() {
  try {
    const p = JSON.parse(fs.readFileSync(STATE_FILE, "utf-8"));
    // Only honor a saved position that is still (mostly) on a live display.
    const onScreen = screen.getAllDisplays().some((d) => {
      const b = d.workArea;
      return p.x + W - 40 > b.x && p.x + 40 < b.x + b.width && p.y + H - 40 > b.y && p.y + 40 < b.y + b.height;
    });
    if (onScreen && Number.isFinite(p.x) && Number.isFinite(p.y)) return { x: p.x, y: p.y };
  } catch {
    /* no saved state */
  }
  return defaultPosition();
}

let saveTimer = null;
function savePosition() {
  if (!win) return;
  const [x, y] = win.getPosition();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
      fs.writeFileSync(STATE_FILE, JSON.stringify({ x, y }));
    } catch {
      /* best effort */
    }
  }, 400);
}

function dispatch(verb, arg) {
  if (!win) return;
  if (verb === "show") {
    clearTimeout(hideFallback);
    if (!win.isVisible()) win.showInactive(); // never steal focus
  } else if (verb === "hide") {
    // The renderer plays its exit animation then sends exit-done; if it is
    // wedged, hide anyway after a beat so `hide` is always honored.
    clearTimeout(hideFallback);
    hideFallback = setTimeout(() => win && win.hide(), 1200);
  }
  win.webContents.send("cmd", { verb, arg: arg || "" });
}

function createWindow() {
  const pos = loadPosition();
  win = new BrowserWindow({
    width: W,
    height: H,
    x: pos.x,
    y: pos.y,
    transparent: !DEBUG,
    backgroundColor: DEBUG ? "#2b2b33" : undefined,
    frame: DEBUG,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: !DEBUG,
    hasShadow: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: false, // preload needs fs to hand the model bytes to the renderer
      backgroundThrottling: false,
      additionalArguments: [
        `--mascot-model=${MODEL}`,
        `--mascot-fps=${FPS}`,
        `--mascot-size=${SIZE}`,
        ...(DEBUG ? ["--mascot-debug"] : []),
      ],
    },
  });
  win.setAlwaysOnTop(true, "screen-saver");
  win.setMenuBarVisibility(false);
  if (!DEBUG) win.setIgnoreMouseEvents(true, { forward: true }); // click-through by default
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  if (DEBUG) {
    win.showInactive();
    win.webContents.openDevTools({ mode: "detach" });
  }
  win.on("closed", () => {
    win = null;
    app.quit();
  });

  // 30 Hz cursor loop: feeds gaze/hover in the renderer and moves the window
  // while dragging. Runs only while visible.
  setInterval(() => {
    if (!win || !win.isVisible()) return;
    const c = screen.getCursorScreenPoint();
    const [wx, wy] = win.getPosition();
    if (dragOffset) win.setPosition(Math.round(c.x - dragOffset.dx), Math.round(c.y - dragOffset.dy));
    win.webContents.send("cursor", { x: c.x - wx, y: c.y - wy, dragging: !!dragOffset });
  }, 33);
}

// -- command bridge ------------------------------------------------------------
function handleLine(l) {
  const parts = l.trim().split(/\s+/);
  const verb = parts[0];
  if (!verb) return;
  if (verb === "stop") return app.quit();
  if (ready) dispatch(verb, parts[1]);
  else pending.push([verb, parts[1]]);
}

function startBridge() {
  if (CTL_PORT > 0) {
    // Normal path: connect back to the Python parent's localhost socket.
    // Socket close/error = parent died -> die too (no orphaned mascots).
    const sock = net.connect({ host: "127.0.0.1", port: CTL_PORT });
    sock.setNoDelay(true);
    const rl = readline.createInterface({ input: sock });
    rl.on("line", handleLine);
    sock.on("close", () => app.quit());
    sock.on("error", () => app.quit());
  } else if (!DEBUG && !SCREENSHOT) {
    // stdin fallback (unreliable on Windows — kept for manual poking on other
    // platforms). Deliberately no quit-on-close: Windows closes it spuriously.
    readline.createInterface({ input: process.stdin }).on("line", handleLine);
  }
}

// -- IPC from renderer --------------------------------------------------------
ipcMain.on("renderer-ready", () => {
  ready = true;
  for (const [v, a] of pending.splice(0)) dispatch(v, a);
  if (SCREENSHOT) {
    dispatch("show", argVal("shot-state", "idle"));
    setTimeout(async () => {
      try {
        const img = await win.webContents.capturePage();
        fs.writeFileSync(SCREENSHOT, img.toPNG());
        console.log("screenshot saved:", SCREENSHOT);
      } catch (e) {
        console.error("screenshot failed:", e);
      }
      app.quit();
    }, 2500);
  }
});
ipcMain.on("renderer-error", (_e, msg) => {
  console.error("renderer error:", msg);
  if (SCREENSHOT) app.quit();
});
ipcMain.on("set-ignore", (_e, ignore) => {
  if (win && !DEBUG) win.setIgnoreMouseEvents(!!ignore, { forward: true });
});
ipcMain.on("drag-start", () => {
  if (!win) return;
  const c = screen.getCursorScreenPoint();
  const [wx, wy] = win.getPosition();
  dragOffset = { dx: c.x - wx, dy: c.y - wy };
});
ipcMain.on("drag-end", () => {
  dragOffset = null;
  savePosition();
});
ipcMain.on("exit-done", () => {
  clearTimeout(hideFallback);
  if (win) win.hide();
});

app.whenReady().then(() => {
  createWindow();
  startBridge();
});
app.on("window-all-closed", () => app.quit());
