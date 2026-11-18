import { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";

/**
 * "Aura Breath" — Procedural Respiratory Animation
 *
 * Injects a low-frequency sine wave into the chest and shoulder bones,
 * scaled by the 27D emotion vector's arousal and serenity dimensions.
 *
 * - High arousal  → faster, shallower breaths (panting)
 * - High serenity → slower, deeper breaths (calm)
 * - Neutral       → gentle idle oscillation so she never looks "frozen"
 *
 * Also maintains a subtle idle sway in the spine and arms for
 * continuous micro-motion between animation triggers.
 */
export class ProceduralAnimation {
  private vrm: VRM;
  private elapsedTime: number = 0;

  /** Breath frequency multiplier from arousal (0-1 → 0.3–2.5 Hz). */
  private breathFrequency: number = 0.8;
  /** Breath amplitude from serenity (0-1 → 0.02–0.08 rad on chest). */
  private breathAmplitude: number = 0.04;

  constructor(vrm: VRM) {
    this.vrm = vrm;
  }

  /**
   * Update breath parameters from the 27D emotion vector.
   * Called by AuraAvatar whenever emotion state changes.
   */
  public setEmotionState(emotion: { arousal: number; serenity: number }): void {
    // Arousal → frequency: 0.3 Hz (sleepy) to 2.5 Hz (excited panting)
    this.breathFrequency = 0.3 + (emotion.arousal ?? 0.5) * 2.2;

    // Serenity → amplitude: calm = deep breaths, stressed = shallow
    this.breathAmplitude = 0.02 + (emotion.serenity ?? 0.5) * 0.06;
  }

  public update(delta: number) {
    this.elapsedTime += delta;
    const t = this.elapsedTime;
    const freq = this.breathFrequency;
    const amp = this.breathAmplitude;

    if (!this.vrm?.humanoid) return;
    const h = this.vrm.humanoid;

    const safeBone = (name: VRMHumanBoneName) => {
      const node = h.getNormalizedBoneNode(name);
      return node ?? null;
    };

    // ---- Aura Breath: spine + chest oscillation --------------------------
    // Primary breath wave (2π * frequency * time)
    const breath = Math.sin(2 * Math.PI * freq * t);

    // Chest expansion (scales with breath amplitude)
    const chest = safeBone("chest");
    if (chest) {
      chest.rotation.x = -0.15 - amp * Math.PI * breath;
    }

    // Spine sway (secondary, slower oscillation for natural feel)
    const spine = safeBone("spine");
    if (spine) {
      spine.rotation.x = -0.2 - amp * 0.6 * Math.PI * breath;
      // Subtle lateral sway
      spine.rotation.z = 0.01 * Math.sin(2 * Math.PI * freq * 0.5 * t);
    }

    // Shoulders rise with inhalation
    const neck = safeBone("neck");
    if (neck) {
      neck.rotation.x = -0.01 * Math.PI * breath * amp;
    }

    // ---- Idle micro-motion (arms, legs) ----------------------------------
    // These prevent the "frozen mannequin" look during silence.
    const idleMicro = 0.005;

    const lUpperArm = safeBone("leftUpperArm");
    if (lUpperArm) {
      lUpperArm.rotation.z = 1.3 + idleMicro * Math.sin(t * 0.7);
      lUpperArm.rotation.x = idleMicro * Math.cos(t * 0.9);
    }

    const rUpperArm = safeBone("rightUpperArm");
    if (rUpperArm) {
      rUpperArm.rotation.z = -1.3 + idleMicro * Math.sin(t * 0.8 + 1);
      rUpperArm.rotation.x = -idleMicro * Math.cos(t * 1.1);
    }

    // Subtle leg sway
    const lUpperLeg = safeBone("leftUpperLeg");
    if (lUpperLeg) {
      lUpperLeg.rotation.z = -0.4 - 0.01 * Math.PI * Math.sin(t * 0.3);
    }

    const rUpperLeg = safeBone("rightUpperLeg");
    if (rUpperLeg) {
      rUpperLeg.rotation.z = 0.4 + 0.01 * Math.PI * Math.sin(t * 0.3);
    }

    // Hands — gentle finger curl oscillation
    const lHand = safeBone("leftHand");
    if (lHand) {
      lHand.rotation.z = idleMicro * 2 * Math.sin(t * 1.3);
    }

    const rHand = safeBone("rightHand");
    if (rHand) {
      rHand.rotation.z = -idleMicro * 2 * Math.sin(t * 1.3 + 0.5);
    }
  }
}
