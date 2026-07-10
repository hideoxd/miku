// Thin access layer over the loaded VRM: normalized humanoid bones, MMD-named
// morph targets, and the extra (non-humanoid) hair bones we sway procedurally.

// Friendly name -> this model's morph target names (Tda-style Miku V4X).
// Each entry may list fallbacks; the first one the model actually has wins.
export const MORPH = {
  blink: ["まばたき"],
  smileEyes: ["笑い"], // happy closed eyes
  wink: ["ウィンク"],
  aa: ["あ"],
  oh: ["お"],
  smileMouth: ["にっこり", "にやり"],
  mouthTri: ["▲"], // small pouty triangle mouth
  blush: ["照れ"],
  surprised: ["びっくり"],
  jitome: ["じと目"], // half-lidded eyes
  tehepero: ["てへぺろ"], // tongue-out tehe
  starEyes: ["星目"],
  lightOff: ["LightOff"], // AutoLuminous bake-off (must be 1 on this model)
};

const HAIR_CHAINS = [
  ["左髪１", "左髪２", "左髪３", "左髪４", "左髪５", "左髪６", "左髪７"],
  ["右髪１", "右髪２", "右髪３", "右髪４", "右髪５", "右髪６", "右髪７"],
];

export class Rig {
  constructor(vrm) {
    this.vrm = vrm;

    // Humanoid bones (normalized space — rest pose is a T-pose).
    this.bones = {};
    for (const name of [
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
      "leftEye",
      "rightEye",
    ]) {
      const node = vrm.humanoid.getNormalizedBoneNode(name);
      if (node) this.bones[name] = node;
    }

    // Morph targets: collect every mesh with a morph dictionary.
    this.morphMeshes = [];
    vrm.scene.traverse((o) => {
      if (o.isMesh && o.morphTargetDictionary && o.morphTargetInfluences) this.morphMeshes.push(o);
    });
    // Resolve friendly names -> actual target name present on this model.
    this.morphName = {};
    for (const [key, candidates] of Object.entries(MORPH)) {
      for (const cand of candidates) {
        if (this.morphMeshes.some((m) => cand in m.morphTargetDictionary)) {
          this.morphName[key] = cand;
          break;
        }
      }
    }

    // Twintail chains (raw scene bones, not humanoid) for procedural sway.
    this.hairChains = HAIR_CHAINS.map((chain) =>
      chain.map((n) => vrm.scene.getObjectByName(n)).filter(Boolean),
    ).filter((c) => c.length > 0);
    // Remember rest rotations so sway is an offset, not an overwrite.
    for (const chain of this.hairChains)
      for (const b of chain) b.userData.restZ = b.rotation.z, (b.userData.restX = b.rotation.x);
  }

  setBone(name, x, y, z) {
    const b = this.bones[name];
    if (b) b.rotation.set(x, y, z);
  }

  setMorph(key, w) {
    const name = this.morphName[key];
    if (!name) return;
    for (const m of this.morphMeshes) {
      const i = m.morphTargetDictionary[name];
      if (i !== undefined) m.morphTargetInfluences[i] = w;
    }
  }

  hasMorph(key) {
    return key in this.morphName;
  }
}

// Exponential smoothing toward a target — every transition becomes fluid for free.
export class Smooth {
  constructor(value = 0, stiffness = 8) {
    this.v = value;
    this.target = value;
    this.k = stiffness;
  }
  update(dt) {
    this.v += (this.target - this.v) * (1 - Math.exp(-this.k * dt));
    return this.v;
  }
}

export function easeOutBack(t) {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
}

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
