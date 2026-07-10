// Per-state personality table. Poses are Euler targets (radians) on VRM
// *normalized* humanoid bones (rest = T-pose, +x pitch fwd, +y yaw left,
// z roll). Morphs use this model's MMD-style target names (see rig.js MORPH).

export const STATES = {
  idle: {
    pose: {},
    morphs: { smileMouth: 0.18 },
    breathAmp: 1.0,
    swayAmp: 1.0,
    blinkEvery: [2.2, 6.0], // seconds, random range
    headBob: 0,
    gazeWeight: 1.0,
  },
  listening: {
    pose: {
      spine: { x: 0.09 }, // lean toward the screen
      head: { x: 0.05 },
    },
    morphs: { surprised: 0.25, smileMouth: 0.1 },
    breathAmp: 0.8,
    swayAmp: 0.4,
    blinkEvery: [3.5, 8.0], // wide-eyed, blinks less
    headBob: 0,
    gazeWeight: 1.15,
  },
  thinking: {
    pose: {
      head: { z: 0.2, x: -0.06 }, // tilt, chin slightly up
      neck: { z: 0.06 },
      // right hand up toward the chin
      rightUpperArm: { x: -0.35, z: 0.95 },
      rightLowerArm: { x: -0.6, y: -1.85 },
      rightHand: { x: -0.35 },
    },
    morphs: { jitome: 0.4, mouthTri: 0.25 },
    breathAmp: 0.9,
    swayAmp: 0.35,
    blinkEvery: [2.5, 5.0],
    headBob: 0,
    gazeWeight: 0.25, // gazes off into space, not at the cursor
  },
  speaking: {
    pose: {
      head: { x: 0.03 },
    },
    morphs: { smileMouth: 0.15, smileEyes: 0.15 },
    breathAmp: 1.3,
    swayAmp: 0.8,
    blinkEvery: [2.5, 6.0],
    headBob: 1.0, // lively talking bob
    gazeWeight: 0.9,
    talkMouth: true, // drives the 'aa' viseme oscillation
  },
};

export function stateFor(name) {
  return STATES[name] || STATES.idle;
}
