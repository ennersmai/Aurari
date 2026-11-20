/**
 * Look-At System: eyes, then head, then a little chest toward a target.
 * Used by the cognitive layer (layer 3) for gaze and head tilt.
 * Deterministic: no Date.now() or Math.random().
 */

import type { ControllerInput, ControllerConfig } from "./layers";
import { Channel } from "./channels";

/** Configuration for look-at behavior. */
export interface LookAtConfig {
  /** Smoothing time constants (seconds to reach target). */
  smoothing: {
    eyes: number;
    head: number;
    chest: number;
  };
  /** Maximum rotation angles (radians). */
  maxAngles: {
    eyes: number;   // Eye rotation limit
    head: number;   // Head rotation limit
    chest: number;  // Chest rotation limit
  };
  /** Whether to enable look-at. */
  enabled: boolean;
}

/** Default look-at configuration. */
export const DEFAULT_LOOKAT_CONFIG: LookAtConfig = {
  smoothing: {
    eyes: 0.15,
    head: 0.3,
    chest: 0.5,
  },
  maxAngles: {
    eyes: Math.PI / 4,      // ±45 degrees
    head: Math.PI / 3,      // ±60 degrees
    chest: Math.PI / 6,     // ±30 degrees
  },
  enabled: true,
};

/** Result of look-at computation. */
export interface LookAtResult {
  /** Eye rotation (yaw, pitch) in radians. */
  eyeRotation: { yaw: number; pitch: number };
  /** Head rotation (yaw, pitch, roll) in radians. */
  headRotation: { yaw: number; pitch: number; roll: number };
  /** Chest rotation (yaw, pitch) in radians. */
  chestRotation: { yaw: number; pitch: number };
  /** Raw target direction (normalized). */
  targetDirection: { x: number; y: number; z: number } | null;
}

/**
 * LookAtSystem computes eye, head, and chest rotations to look at a target.
 * Eyes move first (fastest), then head, then chest (slowest).
 */
export class LookAtSystem {
  private config: LookAtConfig;
  private currentEyeYaw = 0;
  private currentEyePitch = 0;
  private currentHeadYaw = 0;
  private currentHeadPitch = 0;
  private currentHeadRoll = 0;
  private currentChestYaw = 0;
  private currentChestPitch = 0;

  constructor(config: LookAtConfig = DEFAULT_LOOKAT_CONFIG) {
    this.config = config;
  }

  /**
   * Update look-at for one frame.
   * @param t Current time in seconds
   * @param dt Delta time in seconds
   * @param input Controller input (contains gazeTarget)
   * @returns Computed rotations for eyes, head, chest
   */
  update(t: number, dt: number, input: ControllerInput): LookAtResult {
    if (!this.config.enabled || !input.gazeTarget) {
      // No target: smoothly return to neutral
      return this.returnToNeutral(dt);
    }

    // Compute target direction from gaze target
    const targetDir = this.normalize(input.gazeTarget);

    // Compute desired rotations (in radians)
    // Yaw = atan2(x, z), Pitch = atan2(y, sqrt(x^2 + z^2))
    const desiredYaw = Math.atan2(targetDir.x, targetDir.z);
    const desiredPitch = Math.atan2(targetDir.y, Math.sqrt(targetDir.x * targetDir.x + targetDir.z * targetDir.z));

    // Clamp to max angles
    const clampedYaw = this.clamp(desiredYaw, -this.config.maxAngles.eyes, this.config.maxAngles.eyes);
    const clampedPitch = this.clamp(desiredPitch, -this.config.maxAngles.eyes, this.config.maxAngles.eyes);

    // Smoothly interpolate eyes (fastest)
    this.currentEyeYaw = this.lerp(this.currentEyeYaw, clampedYaw, dt, this.config.smoothing.eyes);
    this.currentEyePitch = this.lerp(this.currentEyePitch, clampedPitch, dt, this.config.smoothing.eyes);

    // Head follows eyes but with larger range and slower smoothing
    const headYawTarget = this.clamp(desiredYaw, -this.config.maxAngles.head, this.config.maxAngles.head);
    const headPitchTarget = this.clamp(desiredPitch, -this.config.maxAngles.head, this.config.maxAngles.head);
    this.currentHeadYaw = this.lerp(this.currentHeadYaw, headYawTarget, dt, this.config.smoothing.head);
    this.currentHeadPitch = this.lerp(this.currentHeadPitch, headPitchTarget, dt, this.config.smoothing.head);
    this.currentHeadRoll = this.lerp(this.currentHeadRoll, 0, dt, this.config.smoothing.head); // No roll target

    // Chest follows head but with smaller range and slowest smoothing
    const chestYawTarget = this.clamp(desiredYaw * 0.3, -this.config.maxAngles.chest, this.config.maxAngles.chest);
    const chestPitchTarget = this.clamp(desiredPitch * 0.2, -this.config.maxAngles.chest, this.config.maxAngles.chest);
    this.currentChestYaw = this.lerp(this.currentChestYaw, chestYawTarget, dt, this.config.smoothing.chest);
    this.currentChestPitch = this.lerp(this.currentChestPitch, chestPitchTarget, dt, this.config.smoothing.chest);

    return {
      eyeRotation: { yaw: this.currentEyeYaw, pitch: this.currentEyePitch },
      headRotation: { yaw: this.currentHeadYaw, pitch: this.currentHeadPitch, roll: this.currentHeadRoll },
      chestRotation: { yaw: this.currentChestYaw, pitch: this.currentChestPitch },
      targetDirection: targetDir,
    };
  }

  /** Convert look-at result to channel values for the mixer. */
  resultToChannels(result: LookAtResult): Partial<Record<Channel, number>> {
    return {
      // Eye bones (eyeL, eyeR) - driven by eye rotation
      eyeL: result.eyeRotation.yaw,   // Simplified: yaw for horizontal, pitch for vertical
      eyeR: result.eyeRotation.yaw,
      // Head bone - driven by head rotation
      head: result.headRotation.yaw,  // Simplified: using yaw as primary
      // Chest/spine - driven by chest rotation
      chest: result.chestRotation.yaw,
      spine: result.chestRotation.pitch * 0.5,
      neck: result.headRotation.pitch * 0.5,
    };
  }

  /** Reset to neutral (for testing). */
  reset(): void {
    this.currentEyeYaw = 0;
    this.currentEyePitch = 0;
    this.currentHeadYaw = 0;
    this.currentHeadPitch = 0;
    this.currentHeadRoll = 0;
    this.currentChestYaw = 0;
    this.currentChestPitch = 0;
  }

  /** Update config. */
  setConfig(config: Partial<LookAtConfig>): void {
    this.config = { ...this.config, ...config };
  }

  private returnToNeutral(dt: number): LookAtResult {
    const eyeSpeed = 1 / this.config.smoothing.eyes;
    const headSpeed = 1 / this.config.smoothing.head;
    const chestSpeed = 1 / this.config.smoothing.chest;

    this.currentEyeYaw = this.lerp(this.currentEyeYaw, 0, dt, this.config.smoothing.eyes);
    this.currentEyePitch = this.lerp(this.currentEyePitch, 0, dt, this.config.smoothing.eyes);
    this.currentHeadYaw = this.lerp(this.currentHeadYaw, 0, dt, this.config.smoothing.head);
    this.currentHeadPitch = this.lerp(this.currentHeadPitch, 0, dt, this.config.smoothing.head);
    this.currentHeadRoll = this.lerp(this.currentHeadRoll, 0, dt, this.config.smoothing.head);
    this.currentChestYaw = this.lerp(this.currentChestYaw, 0, dt, this.config.smoothing.chest);
    this.currentChestPitch = this.lerp(this.currentChestPitch, 0, dt, this.config.smoothing.chest);

    return {
      eyeRotation: { yaw: this.currentEyeYaw, pitch: this.currentEyePitch },
      headRotation: { yaw: this.currentHeadYaw, pitch: this.currentHeadPitch, roll: this.currentHeadRoll },
      chestRotation: { yaw: this.currentChestYaw, pitch: this.currentChestPitch },
      targetDirection: null,
    };
  }

  private lerp(current: number, target: number, dt: number, smoothing: number): number {
    if (smoothing <= 0) return target;
    const factor = 1 - Math.exp(-dt / smoothing);
    return current + (target - current) * factor;
  }

  private clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
  }

  private normalize(v: { x: number; y: number; z: number }): { x: number; y: number; z: number } {
    const len = Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
    if (len === 0) return { x: 0, y: 0, z: -1 };
    return { x: v.x / len, y: v.y / len, z: v.z / len };
  }
}