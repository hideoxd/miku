// Hover / drag / headpat, and the click-through toggle.
//
// Hit-testing uses projected humanoid-bone circles (head, chest, hips) instead
// of mesh raycasts — three cheap distance checks per cursor tick, robust across
// three.js versions. Hovering any circle makes the window clickable; leaving it
// restores click-through. Mousedown then movement (or a hold) = drag the OS
// window; a quick release on her head = headpat.

import { Vector3 } from "three";
import { clamp } from "./rig.js";

const v = new Vector3();
const v2 = new Vector3();

export class Interact {
  constructor(vrm, camera, canvas, animator, onHeadpat) {
    this.vrm = vrm;
    this.camera = camera;
    this.canvas = canvas;
    this.animator = animator;
    this.onHeadpat = onHeadpat;

    this.zones = []; // {x, y, r, isHead} in canvas px
    this.ignored = true; // current click-through state (start ignored)
    this.visible = false;
    this.dragging = false;
    this.press = null; // {x, y, t, onHead}

    canvas.addEventListener("mousedown", (e) => this._down(e));
    window.addEventListener("mouseup", (e) => this._up(e));
    window.addEventListener("mousemove", (e) => this._move(e));
  }

  setVisible(vis) {
    this.visible = vis;
    if (!vis) this._setIgnore(true);
  }

  /** Recompute hit zones from bone positions (each frame, cheap). */
  updateZones() {
    const zones = [];
    const half = { w: this.canvas.clientWidth / 2, h: this.canvas.clientHeight / 2 };
    const project = (bone) => {
      const node = this.vrm.humanoid.getNormalizedBoneNode(bone);
      if (!node) return null;
      node.getWorldPosition(v);
      v2.copy(v).project(this.camera);
      return { x: (v2.x + 1) * half.w, y: (1 - v2.y) * half.h };
    };
    const head = project("head");
    const chest = project("upperChest") || project("spine");
    const hips = project("hips");
    // Scale radii off the projected torso length so they track window size.
    const torso = head && hips ? Math.hypot(head.x - hips.x, head.y - hips.y) : 100;
    if (head) zones.push({ ...head, y: head.y - torso * 0.1, r: torso * 0.42, isHead: true });
    if (chest) zones.push({ ...chest, r: torso * 0.34, isHead: false });
    if (hips) zones.push({ ...hips, r: torso * 0.36, isHead: false });
    this.zones = zones;
  }

  /** Driven by the 30 Hz cursor IPC (works even while click-through). */
  onCursor(c) {
    if (!this.visible) return;
    if (this.dragging) return; // stay clickable while dragging
    const over = this._hit(c.x, c.y) !== null;
    this._setIgnore(!over);
  }

  _hit(x, y) {
    for (const z of this.zones) if (Math.hypot(x - z.x, y - z.y) < z.r) return z;
    return null;
  }

  _setIgnore(ignore) {
    if (ignore === this.ignored) return;
    this.ignored = ignore;
    window.mascot.setIgnore(ignore);
  }

  _down(e) {
    if (!this.visible) return;
    const z = this._hit(e.clientX, e.clientY);
    if (!z) return;
    this.press = { x: e.screenX, y: e.screenY, t: performance.now(), onHead: z.isHead };
  }

  _move(e) {
    if (!this.press || this.dragging) return;
    const moved = Math.hypot(e.screenX - this.press.x, e.screenY - this.press.y);
    if (moved > 4 || performance.now() - this.press.t > 300) this._startDrag();
  }

  _startDrag() {
    this.dragging = true;
    this.animator.setDragging(true);
    window.mascot.dragStart();
  }

  _up(e) {
    if (this.dragging) {
      this.dragging = false;
      this.animator.setDragging(false);
      window.mascot.dragEnd();
    } else if (this.press && this.press.onHead && performance.now() - this.press.t < 300) {
      this.onHeadpat();
    }
    this.press = null;
  }
}
