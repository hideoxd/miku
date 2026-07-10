// Bridge between the sandboxed page and Electron. Also hands the VRM bytes to
// the renderer as an ArrayBuffer — Chromium's fetch() refuses file:// URLs, so
// GLTFLoader.parse(bytes) is the clean way to load a local model.

const { contextBridge, ipcRenderer } = require("electron");
const fs = require("fs");

function arg(name, def) {
  const hit = process.argv.find((a) => a.startsWith(`--mascot-${name}=`));
  return hit ? hit.split("=").slice(1).join("=") : def;
}

contextBridge.exposeInMainWorld("mascot", {
  args: {
    model: arg("model", ""),
    fps: parseInt(arg("fps", "30"), 10),
    size: parseInt(arg("size", "240"), 10),
    debug: process.argv.includes("--mascot-debug"),
  },
  readModel: () => {
    const buf = fs.readFileSync(arg("model", ""));
    return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  },
  onCommand: (cb) => ipcRenderer.on("cmd", (_e, m) => cb(m)),
  onCursor: (cb) => ipcRenderer.on("cursor", (_e, m) => cb(m)),
  setIgnore: (v) => ipcRenderer.send("set-ignore", v),
  dragStart: () => ipcRenderer.send("drag-start"),
  dragEnd: () => ipcRenderer.send("drag-end"),
  exitDone: () => ipcRenderer.send("exit-done"),
  ready: () => ipcRenderer.send("renderer-ready"),
  reportError: (msg) => ipcRenderer.send("renderer-error", String(msg)),
});
