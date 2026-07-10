// Cursor gaze: eyes lead (via the VRM lookAt target), head and neck lag behind
// with softer smoothing — the offset in stiffness is what makes it feel alive.
// When the cursor has been still for a while she wanders off, glancing around.

import { Object3D } from "three";
import { Smooth, clamp } from "./rig.js";

export class Gaze {
  constructor(vrm, camera, scene, winW, winH) {
    this.vrm = vrm;
    this.camera = camera;
    this.winW = winW;
    this.winH = winH;

    // Lives in the *root* scene so vrm.scene's VRM0 flip can't mirror it.
    this.target = new Object3D();
    scene.add(this.target);
    if (vrm.lookAt) vrm.lookAt.target = this.target;

    this.yaw = new Smooth(0, 4.5); // head lags…
    this.pitch = new Smooth(0, 4.5);
    this.eyeX = new Smooth(0, 14); // …eyes lead
    this.eyeY = new Smooth(0, 14);

    this.lastCursor = { x: winW / 2, y: winH / 2 };
    this.idleFor = 0;
    this.wanderT = 0;
    this.wander = { x: 0, y: 0 };
  }

  onCursor(c) {
    if (Math.abs(c.x - this.lastCursor.x) + Math.abs(c.y - this.lastCursor.y) > 2) this.idleFor = 0;
    this.lastCursor = c;
  }

  /** Called each frame; writes head/neck offsets into the animator. */
  update(dt, animator, weight) {
    this.idleFor += dt;

    // Normalized cursor position relative to the window (can exceed ±1 when
    // the cursor is far away on screen — clamp keeps her from over-rotating).
    let nx = clamp((this.lastCursor.x / this.winW - 0.5) * 2, -1.6, 1.6);
    let ny = clamp((this.lastCursor.y / this.winH - 0.42) * 2, -1.2, 1.2);

    if (this.idleFor > 8) {
      // Bored: glance somewhere new every few seconds.
      if ((this.wanderT -= dt) <= 0) {
        this.wanderT = 1.5 + Math.random() * 2.5;
        this.wander = { x: (Math.random() - 0.5) * 1.6, y: (Math.random() - 0.55) * 0.8 };
      }
      nx = this.wander.x;
      ny = this.wander.y;
    }

    // Window x-axis: cursor right of her = negative yaw (screen x grows right,
    // model yaw + turns her to *her* left, which is screen-right… VRM yaw +y is
    // to her left = viewer right for a facing model). Sign tuned visually.
    this.yaw.target = nx * 0.42 * weight;
    this.pitch.target = ny * 0.30 * weight;
    this.eyeX.target = nx;
    this.eyeY.target = ny;

    const yaw = this.yaw.update(dt);
    const pitch = this.pitch.update(dt);
    animator.headExtra = { x: pitch * 0.7, y: yaw * 0.7, z: 0 };
    animator.neckExtra = { x: pitch * 0.3, y: yaw * 0.3, z: 0 };

    // Eye target floats in front of her face, offset by the cursor.
    const ex = this.eyeX.update(dt);
    const ey = this.eyeY.update(dt);
    const head = this.vrm.humanoid.getNormalizedBoneNode("head");
    if (head) {
      head.getWorldPosition(this.target.position);
      this.target.position.x += ex * 0.9;
      this.target.position.y += -ey * 0.6;
      this.target.position.z += 1.4; // toward the camera
    }
  }
}
