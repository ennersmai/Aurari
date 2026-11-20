/**
 * Cognitive Layer (Layer 3): maps each cognitive state to gaze target, head tilt
 * and brow modifiers, with smooth transitions between states.
 *
 * Values are defined inline as JSON-like constants. Groups: upperFace, eyes, head
 * (per ownership.json, cognitive has priority 3 in each).
 */

import type { Layer, LayerOutput, ControllerInput } from "./layers";
import { Channel, CHANNELS_BY_GROUP } from "./channels";

/** Target configuration for a single cognitive state. */
interface CognitiveStateConfig {
  /** Where the avatar looks (null = no directed gaze). */
  gazeTarget: { x: number; y: number; z: number } | null;
  /** Head tilt in radians (positive = tilt to the right). */
  headTilt: number;
  /** ARKit blend shape modifiers for the brow area. */
  browModifiers: Record<string, number>;
}

/**
 * Mapping from cognitive state to gaze target, head tilt and brow modifiers.
 * Values in JSON-like constants.
 *
 * States (from PRD avatar 8 / AvatarStateMachine):
 *   attending, recalling, thinking, unsure, found_it, surprised,
 *   working, curious, resting, idle
 */
const COGNITIVE_MAP: Record<string, CognitiveStateConfig> = {
  attending: {
    gazeTarget: { x: 0, y: 0, z: -1 },
    headTilt: 0.0,
    browModifiers: { browInnerUp: 0.2, browOuterUpLeft: 0.1, browOuterUpRight: 0.1 },
  },
  recalling: {
    gazeTarget: { x: -0.5, y: 0.2, z: -1 },
    headTilt: -0.1,
    browModifiers: { browInnerUp: 0.3, browOuterUpLeft: 0.2, browOuterUpRight: 0.2 },
  },
  thinking: {
    gazeTarget: { x: -0.3, y: 0.1, z: -1 },
    headTilt: -0.15,
    browModifiers: { browInnerUp: 0.4, browOuterUpLeft: 0.3, browOuterUpRight: 0.3 },
  },
  unsure: {
    gazeTarget: null,
    headTilt: 0.1,
    browModifiers: { browInnerUp: 0.5, browOuterUpLeft: 0.4, browOuterUpRight: 0.4 },
  },
  found_it: {
    gazeTarget: { x: 0, y: 0, z: -1 },
    headTilt: 0.0,
    browModifiers: { browInnerUp: 0.1, browOuterUpLeft: 0.05, browOuterUpRight: 0.05 },
  },
  surprised: {
    gazeTarget: { x: 0, y: 0.1, z: -1 },
    headTilt: 0.0,
    browModifiers: { browInnerUp: 0.8, browOuterUpLeft: 0.6, browOuterUpRight: 0.6 },
  },
  working: {
    gazeTarget: { x: 0, y: -0.1, z: -1 },
    headTilt: -0.05,
    browModifiers: { browInnerUp: 0.2, browOuterUpLeft: 0.1, browOuterUpRight: 0.1 },
  },
  curious: {
    gazeTarget: { x: 0.3, y: 0.1, z: -1 },
    headTilt: 0.15,
    browModifiers: { browInnerUp: 0.3, browOuterUpLeft: 0.2, browOuterUpRight: 0.2 },
  },
  resting: {
    gazeTarget: null,
    headTilt: 0.0,
    browModifiers: {},
  },
  idle: {
    gazeTarget: null,
    headTilt: 0.0,
    browModifiers: {},
  },
};

/** Default config when a state is not found in the map. */
const DEFAULT_STATE_CONFIG: CognitiveStateConfig = COGNITIVE_MAP["attending"];

/** Seconds to fully transition from current value to target value. */
const TRANSITION_SPEED = 2.0;

/** Maximum gaze angle (radians) applied to eye bones. */
const MAX_GAZE_ANGLE = 0.4;

/** Brow channels the cognitive layer writes. */
const BROW_CHANNELS: readonly string[] = [
  "browDownLeft",
  "browDownRight",
  "browInnerUp",
  "browOuterUpLeft",
  "browOuterUpRight",
];

/**
 * CognitiveLayer produces gaze, head tilt and brow modifier outputs from the
 * current cognitive state, smoothly transitioning between states.
 */
export class CognitiveLayer implements Layer {
  readonly name = "cognitive" as const;
  readonly groups = ["upperFace", "eyes", "head"] as const;

  private currentGazeTarget: { x: number; y: number; z: number } | null = null;
  private currentHeadTilt = 0;
  private currentBrowModifiers: Record<string, number> = {};

  update(t: number, dt: number, input: ControllerInput): LayerOutput {
    const output: LayerOutput = {};

    const state = input.cognitiveState || "attending";
    const config = COGNITIVE_MAP[state] ?? DEFAULT_STATE_CONFIG;

    // Smoothly transition gaze target toward the state's target
    this.currentGazeTarget = this.lerpGazeTarget(this.currentGazeTarget, config.gazeTarget, dt);
    this.currentHeadTilt = this.lerpValue(this.currentHeadTilt, config.headTilt, dt);
    this.currentBrowModifiers = this.lerpBrowModifiers(this.currentBrowModifiers, config.browModifiers, dt);

    // Convert gaze target to eye bone rotations (yaw + pitch)
    if (this.currentGazeTarget) {
      const yaw = Math.max(-MAX_GAZE_ANGLE, Math.min(MAX_GAZE_ANGLE, this.currentGazeTarget.x));
      const pitch = Math.max(-MAX_GAZE_ANGLE, Math.min(MAX_GAZE_ANGLE, this.currentGazeTarget.y));
      output.eyeL = yaw;
      output.eyeR = yaw;
      // Eyes look up/down via pitch (stored on eye bones too for the placeholder head)
      output.eyeL = yaw + pitch * 0.5;
      output.eyeR = yaw - pitch * 0.5;
    }

    // Head tilt
    output.head = this.currentHeadTilt;

    // Brow modifiers
    for (const channel of BROW_CHANNELS) {
      const value = this.currentBrowModifiers[channel];
      if (value !== undefined && value !== 0) {
        output[channel as Channel] = value;
      }
    }

    return this.filterOutput(output);
  }

  /** Linearly interpolate a gaze target toward the target over dt. */
  private lerpGazeTarget(
    current: { x: number; y: number; z: number } | null,
    target: { x: number; y: number; z: number } | null,
    dt: number
  ): { x: number; y: number; z: number } | null {
    if (!target) return null;
    if (!current) return { ...target };
    const alpha = Math.min(1, dt * TRANSITION_SPEED);
    return {
      x: current.x + (target.x - current.x) * alpha,
      y: current.y + (target.y - current.y) * alpha,
      z: current.z + (target.z - current.z) * alpha,
    };
  }

  /** Linearly interpolate a scalar value toward the target over dt. */
  private lerpValue(current: number, target: number, dt: number): number {
    const alpha = Math.min(1, dt * TRANSITION_SPEED);
    return current + (target - current) * alpha;
  }

  /** Linearly interpolate brow modifier values toward the targets over dt. */
  private lerpBrowModifiers(
    current: Record<string, number>,
    target: Record<string, number>,
    dt: number
  ): Record<string, number> {
    const alpha = Math.min(1, dt * TRANSITION_SPEED);
    const result: Record<string, number> = { ...current };
    for (const [channel, targetValue] of Object.entries(target)) {
      const currentValue = result[channel] ?? 0;
      result[channel] = currentValue + (targetValue - currentValue) * alpha;
    }
    // Decay any current modifiers not present in the target
    for (const channel of Object.keys(result)) {
      if (!(channel in target)) {
        result[channel] = result[channel]! * (1 - alpha);
        if (Math.abs(result[channel]!) < 0.001) {
          delete result[channel];
        }
      }
    }
    return result;
  }

  /** Filter output to only channels this layer owns. */
  private filterOutput(output: LayerOutput): LayerOutput {
    const allowed = new Set<Channel>();
    for (const group of this.groups) {
      for (const ch of CHANNELS_BY_GROUP[group]) {
        allowed.add(ch);
      }
    }
    const filtered: LayerOutput = {};
    for (const [ch, val] of Object.entries(output)) {
      if (allowed.has(ch as Channel)) {
        filtered[ch as Channel] = val;
      }
    }
    return filtered;
  }

  reset(): void {
    this.currentGazeTarget = null;
    this.currentHeadTilt = 0;
    this.currentBrowModifiers = {};
  }
}
