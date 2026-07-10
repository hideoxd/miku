// Layered procedural animator. Every frame we compose, in order:
//   1. base pose (T-pose arms brought down)
//   2. smoothed state pose + morphs (states.js)
//   3. ambient life: breathing, sway, blink scheduler, talking mouth
//   4. gaze (head/neck follow, applied by gaze.js via headExtra)
//   5. one-shot gestures: entrance jump+wave, exit drop, headpat, drag dangle
// then hand over to vrm.update(dt).

import { stateFor } from "./states.js";
import { Smooth, easeOutBack, clamp } from "./rig.js";

const BONES = [
  "hips",
  "spine",
  "chest",
  "upperChest",
  "neck",
  "head",
  "leftShoulder",
  "rightShoulder",
  "leftUpperArm",
  "rightUpperArm",
  "leftLowerArm",
  "rightLowerArm",
  "leftHand",
  "rightHand",
];

// Arms down from the T-pose (signs verified visually: +z lowers the left arm).
const BASE_POSE = {
  leftUpperArm: { z: 1.18 },
  rightUpperArm: { z: -1.18 },
  leftLowerArm: { z: 0.12 },
  rightLowerArm: { z: -0.12 },
};

const MORPH_KEYS = ["smileEyes", "smileMouth", "surprised", "jitome", "blush", "mouthTri", "starEyes"];

export class Animator {
  constructor(rig) {
    this.rig = rig;
    this.t = 0;
    this.stateName = "idle";
    this.state = stateFor("idle");

    // Smoothed channels for every pose axis and slow morph.
    this.ch = {};
    for (const b of BONES) this.ch[b] = { x: new Smooth(0, 6), y: new Smooth(0, 6), z: new Smooth(0, 6) };
    this.morphCh = {};
    for (const k of MORPH_KEYS) this.morphCh[k] = new Smooth(0, 7);

    // Params (breath/sway/bob amplitudes) also glide between states.
    this.breathAmp = new Smooth(1, 4);
    this.swayAmp = new Smooth(1, 4);
    this.headBob = new Smooth(0, 4);

    // Blink scheduler.
    this.nextBlink = 2 + Math.random() * 3;
    this.blinkT = -1; // >=0 while a blink is playing

    // Extra rotations merged in by gaze.js each frame.
    this.headExtra = { x: 0, y: 0, z: 0 };
    this.neckExtra = { x: 0, y: 0, z: 0 };

    // One-shot gesture: {name, t, dur}
    this.gesture = null;
    this.onGestureEnd = null;
    this.dragging = false;

    // Root offsets for entrance/exit (model slides inside the fixed window).
    this.rootY = 0;
    this.rootScaleY = 1;
    this.hidden = true;

    this._applyStateTargets();
  }

  setState(name) {
    if (name === this.stateName) return;
    this.stateName = name;
    this.state = stateFor(name);
    this._applyStateTargets();
  }

  _applyStateTargets() {
    const pose = this.state.pose;
    for (const b of BONES) {
      const base = BASE_POSE[b] || {};
      const st = pose[b] || {};
      this.ch[b].x.target = (base.x || 0) + (st.x || 0);
      this.ch[b].y.target = (base.y || 0) + (st.y || 0);
      this.ch[b].z.target = (base.z || 0) + (st.z || 0);
    }
    for (const k of MORPH_KEYS) this.morphCh[k].target = this.state.morphs[k] || 0;
    this.breathAmp.target = this.state.breathAmp;
    this.swayAmp.target = this.state.swayAmp;
    this.headBob.target = this.state.headBob;
  }

  play(name, onEnd) {
    const dur = { entrance: 1.6, exit: 0.45, headpat: 1.6 }[name] || 1;
    this.gesture = { name, t: 0, dur };
    this.onGestureEnd = onEnd || null;
    if (name === "entrance") this.hidden = false;
  }

  setDragging(d) {
    this.dragging = d;
  }

  update(dt) {
    dt = Math.min(dt, 0.1);
    this.t += dt;
    const t = this.t;
    const rig = this.rig;

    // ---- smoothed state pose ------------------------------------------------
    const rot = {};
    for (const b of BONES) rot[b] = { x: this.ch[b].x.update(dt), y: this.ch[b].y.update(dt), z: this.ch[b].z.update(dt) };
    const breath = this.breathAmp.update(dt);
    const sway = this.swayAmp.update(dt);
    const bob = this.headBob.update(dt);

    // ---- ambient life ---------------------------------------------------------
    const br = Math.sin(t * 1.7) * 0.028 * breath;
    rot.upperChest.x += br;
    rot.spine.x += br * 0.5;
    rot.hips.z += Math.sin(t * 0.5) * 0.022 * sway;
    rot.upperChest.z += Math.sin(t * 0.5 + 0.6) * 0.012 * sway;
    // Idle arm micro-motion so she never looks frozen.
    rot.leftUpperArm.z += Math.sin(t * 0.8) * 0.02 * sway;
    rot.rightUpperArm.z -= Math.sin(t * 0.8 + 1.1) * 0.02 * sway;
    if (bob > 0.01) {
      rot.head.x += Math.sin(t * 4.2) * 0.045 * bob;
      rot.head.z += Math.sin(t * 2.6) * 0.02 * bob;
    }

    // ---- gaze (computed by gaze.js) -----------------------------------------
    rot.head.x += this.headExtra.x;
    rot.head.y += this.headExtra.y;
    rot.head.z += this.headExtra.z;
    rot.neck.x += this.neckExtra.x;
    rot.neck.y += this.neckExtra.y;

    // ---- gestures -------------------------------------------------------------
    let morphOverride = {};
    if (this.dragging) {
      // Carried: arms dangle up a touch, surprised face.
      rot.leftUpperArm.z -= 0.35;
      rot.rightUpperArm.z += 0.35;
      rot.hips.z += Math.sin(t * 6) * 0.04;
      morphOverride.surprised = 0.55;
    }
    if (this.gesture) {
      const g = this.gesture;
      g.t += dt;
      const p = clamp(g.t / g.dur, 0, 1);
      if (g.name === "entrance") {
        // Springy rise from below + squash-stretch pop (first 0.55s), then wave.
        const rise = clamp(g.t / 0.55, 0, 1);
        this.rootY = (easeOutBack(rise) - 1) * 1.0;
        this.rootScaleY = 1 + Math.sin(clamp(rise, 0, 1) * Math.PI) * 0.06;
        const wt = g.t - 0.35;
        if (wt > 0 && wt < 1.1) {
          // Right-hand wave: arm up-out, forearm wagging.
          const in_ = clamp(wt / 0.18, 0, 1) * clamp((1.1 - wt) / 0.2, 0, 1);
          rot.rightUpperArm.z += 2.25 * in_; // undo the down-pose, raise past shoulder
          rot.rightUpperArm.x += -0.25 * in_;
          rot.rightLowerArm.z += (-0.5 + Math.sin(wt * 14) * 0.55) * in_;
          rot.head.z += -0.12 * in_;
        }
        morphOverride.smileEyes = Math.max(morphOverride.smileEyes || 0, Math.sin(p * Math.PI) * 0.9);
        morphOverride.smileMouth = Math.max(morphOverride.smileMouth || 0, Math.sin(p * Math.PI) * 0.8);
      } else if (g.name === "exit") {
        const e = p * p;
        this.rootY = -1.4 * e;
        rot.head.x += 0.2 * e; // little bow as she sinks away
      } else if (g.name === "headpat") {
        // Blushy nuzzle: happy closed eyes, blush, tiny head wobble.
        const env = Math.sin(p * Math.PI);
        morphOverride.smileEyes = 0.95 * env;
        morphOverride.blush = 1.0 * env;
        morphOverride.smileMouth = 0.85 * env;
        rot.head.z += Math.sin(g.t * 9) * 0.06 * env;
        rot.head.x += 0.08 * env;
      }
      if (g.t >= g.dur) {
        this.gesture = null;
        if (g.name === "entrance") this.rootY = 0, (this.rootScaleY = 1);
        if (g.name === "exit") this.hidden = true;
        const cb = this.onGestureEnd;
        this.onGestureEnd = null;
        if (cb) cb();
      }
    }

    // ---- blink ------------------------------------------------------------------
    let blink = 0;
    if (this.blinkT >= 0) {
      this.blinkT += dt;
      const d = 0.13;
      blink = this.blinkT < d ? Math.sin((this.blinkT / d) * Math.PI) : 0;
      if (this.blinkT >= d) {
        this.blinkT = -1;
        const [lo, hi] = this.state.blinkEvery;
        this.nextBlink = lo + Math.random() * (hi - lo);
      }
    } else if ((this.nextBlink -= dt) <= 0) {
      this.blinkT = 0;
    }

    // ---- talking mouth ------------------------------------------------------------
    let aa = 0;
    if (this.state.talkMouth) {
      aa = clamp(0.12 + 0.5 * Math.abs(Math.sin(t * 9.5) + 0.3 * Math.sin(t * 23)), 0, 0.85);
    }

    // ---- twintail sway --------------------------------------------------------------
    for (let c = 0; c < rig.hairChains.length; c++) {
      const chain = rig.hairChains[c];
      const dir = c === 0 ? 1 : -1;
      for (let i = 0; i < chain.length; i++) {
        const b = chain[i];
        const phase = t * 1.3 + i * 0.55 + c * Math.PI;
        const amp = 0.02 + i * 0.012;
        b.rotation.z = b.userData.restZ + Math.sin(phase) * amp * sway * dir;
        b.rotation.x = b.userData.restX + Math.cos(phase * 0.8) * amp * 0.5 * (this.dragging ? 3 : 1);
      }
    }

    // ---- write to the rig ----------------------------------------------------------
    for (const b of BONES) rig.setBone(b, rot[b].x, rot[b].y, rot[b].z);
    for (const k of MORPH_KEYS) {
      const v = Math.max(this.morphCh[k].update(dt), morphOverride[k] || 0);
      rig.setMorph(k, v);
    }
    // Blink combines with happy-closed eyes (whichever closes more wins).
    rig.setMorph("blink", clamp(blink, 0, 1));
    rig.setMorph("aa", aa);
  }
}
