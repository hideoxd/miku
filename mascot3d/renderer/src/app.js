// Renderer bootstrap: load the VRM, build the rig/animator/gaze/interaction,
// and run a 30 fps (capped) render loop that pauses entirely while hidden.

import {
  WebGLRenderer,
  Scene,
  PerspectiveCamera,
  DirectionalLight,
  AmbientLight,
  Box3,
  Vector3,
  Clock,
} from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import { Rig } from "./rig.js";
import { Animator } from "./animator.js";
import { Gaze } from "./gaze.js";
import { Interact } from "./interact.js";

const { args } = window.mascot;

async function main() {
  const canvas = document.getElementById("stage");
  const W = canvas.clientWidth;
  const H = canvas.clientHeight;

  const renderer = new WebGLRenderer({
    canvas,
    alpha: true,
    antialias: true,
    powerPreference: "high-performance",
  });
  // Supersample: render at 2x the window resolution and let it downscale.
  // Even on a 100%-scaling display this sharpens the face/hair dramatically
  // (the model is small on screen, so 1x reads as blurry). Capped for the iGPU.
  const SS = Math.min(2, (window.devicePixelRatio || 1) * 2);
  renderer.setPixelRatio(SS);
  renderer.setSize(W, H, false);
  renderer.setClearColor(0x000000, 0);

  const scene = new Scene();
  const camera = new PerspectiveCamera(27, W / H, 0.1, 20);
  scene.add(new AmbientLight(0xffffff, 0.72));
  const sun = new DirectionalLight(0xffffff, 1.05);
  sun.position.set(0.4, 1.2, 1.5);
  scene.add(sun);
  const rim = new DirectionalLight(0xdff4ff, 0.35); // soft cool rim for depth
  rim.position.set(-0.8, 0.6, -0.7);
  scene.add(rim);

  // ---- load the model (bytes via preload; fetch() can't read file://) ----------
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const bytes = window.mascot.readModel();
  const gltf = await new Promise((res, rej) => loader.parse(bytes, "", res, rej));
  const vrm = gltf.userData.vrm;
  VRMUtils.combineSkeletons(gltf.scene);
  VRMUtils.rotateVRM0(vrm); // VRM 0.x faces away by default
  scene.add(vrm.scene);

  // Crisp textures: max anisotropic filtering + no over-aggressive mip blur.
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  vrm.scene.traverse((o) => {
    if (!o.isMesh) return;
    for (const mat of Array.isArray(o.material) ? o.material : [o.material]) {
      if (mat && mat.map) {
        mat.map.anisotropy = maxAniso;
        mat.map.needsUpdate = true;
      }
    }
  });

  const rig = new Rig(vrm);
  rig.setMorph("lightOff", 1); // this Tda model bakes AutoLuminous glow off via a morph

  // ---- frame her: full body, feet at the window bottom --------------------------
  const animator = new Animator(rig);
  animator.update(0.001); // settle the base pose before measuring
  vrm.update(0.001);
  const box = new Box3().setFromObject(vrm.scene);
  const size = box.getSize(new Vector3());
  const modelH = size.y;
  const fit = (modelH * 1.1) / 2 / Math.tan(((camera.fov / 2) * Math.PI) / 180);
  camera.position.set(0, box.min.y + modelH * 0.52, fit);
  camera.lookAt(0, box.min.y + modelH * 0.52, 0);

  const gaze = new Gaze(vrm, camera, scene, W, H);
  const interact = new Interact(vrm, camera, canvas, animator, () => animator.play("headpat"));

  // ---- render loop (fps-capped, paused while hidden) ------------------------------
  const clock = new Clock();
  const frameInterval = 1 / Math.max(10, args.fps || 30);
  let running = false;
  let acc = 0;

  function frame() {
    if (!running) return;
    requestAnimationFrame(frame);
    acc += clock.getDelta();
    if (acc < frameInterval) return;
    const dt = Math.min(acc, 0.1);
    acc = 0;

    animator.update(dt);
    gaze.update(dt, animator, animator.state.gazeWeight);
    interact.updateZones();
    vrm.scene.position.y = animator.rootY * modelH;
    vrm.scene.scale.y = animator.rootScaleY;
    vrm.update(dt);
    renderer.render(scene, camera);
  }

  function start() {
    if (running) return;
    running = true;
    clock.getDelta(); // reset so the first dt isn't huge
    requestAnimationFrame(frame);
  }
  function stop() {
    running = false;
  }

  // ---- commands from the Python service (via main's stdin bridge) ------------------
  window.mascot.onCommand(({ verb, arg }) => {
    if (verb === "show") {
      const state = arg || "listening";
      // A show that lands mid-exit cancels the exit (else its exit-done would
      // hide the window right after we showed it).
      if (animator.gesture && animator.gesture.name === "exit") {
        animator.gesture = null;
        animator.onGestureEnd = null;
        animator.rootY = 0;
      }
      animator.setState(state);
      interact.setVisible(true);
      start();
      if (animator.hidden) animator.play("entrance");
    } else if (verb === "state") {
      animator.setState(arg || "idle");
    } else if (verb === "hide") {
      if (animator.hidden) {
        window.mascot.exitDone();
        return;
      }
      animator.setState("idle");
      animator.play("exit", () => {
        window.mascot.exitDone();
        interact.setVisible(false);
        stop();
      });
    }
    // Unknown verbs are ignored so the protocol can grow.
  });

  window.mascot.onCursor((c) => {
    gaze.onCursor(c);
    interact.onCursor(c);
  });

  // In debug mode show her immediately so there's something to look at.
  if (args.debug) {
    animator.hidden = false;
    interact.setVisible(true);
    start();
  }

  // First paint before announcing readiness (avoids a blank flash on `show`).
  animator.update(0.016);
  vrm.update(0.016);
  renderer.render(scene, camera);
  window.mascot.ready();
}

window.addEventListener("error", (e) => window.mascot.reportError(e.message || String(e)));
window.addEventListener("unhandledrejection", (e) => window.mascot.reportError(e.reason?.stack || String(e.reason)));

main().catch((e) => window.mascot.reportError(e?.stack || String(e)));
