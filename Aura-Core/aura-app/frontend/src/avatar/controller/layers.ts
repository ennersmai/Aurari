/**
 * Layer interfaces and types for the avatar controller.
 * Six layers each produce partial channel values per frame.
 */

import type { Channel, ChannelGroup } from "./channels.js";

/** Input provided to each layer every frame. */
export interface ControllerInput {
  /** Current time in seconds (monotonic, passed in for determinism). */
  t: number;
  /** Delta time in seconds since last frame. */
  dt: number;
  /** Emotional deviation from baseline (27 dimensions). */
  emotionDeviation: Record<string, number>;
  /** Current cognitive state from the pipeline. */
  cognitiveState: string;
  /** Whether speech is currently active. */
  isSpeaking: boolean;
  /** Current viseme weights (15 visemes) when speaking. */
  visemes: Record<string, number>;
  /** Look-at target in world space (or null). */
  gazeTarget: { x: number; y: number; z: number } | null;
  /** Event pulses active this frame (from events layer). */
  eventPulses: EventPulse[];
  /** Gesture clip currently playing (if any). */
  gestureClip: GestureClip | null;
  /** Avatar config (for seeded noise, etc.). */
  config: ControllerConfig;
}

/** Configuration for the controller (seeded noise, timing, etc.). */
export interface ControllerConfig {
  /** Seed for deterministic noise functions. */
  noiseSeed: number;
  /** Idle breathing rate (cycles per second). */
  breathingRate: number;
  /** Idle weight shift rate. */
  weightShiftRate: number;
  /** Blink interval range [min, max] in seconds. */
  blinkInterval: [number, number];
  /** Look-at smoothing time constants. */
  lookAtSmoothing: {
    eyes: number;
    head: number;
    chest: number;
  };
  /** Mood from emotion engine (valence: -1 to 1, arousal: 0 to 1). Null until E4. */
  mood?: { valence: number; arousal: number } | null;
}

/** An event pulse (surprise, amusement, nod, etc.). */
export interface EventPulse {
  /** Unique id for this pulse. */
  id: string;
  /** Type of event. */
  type: "surprise" | "amusement" | "nod" | "custom";
  /** Strength 0-1. */
  strength: number;
  /** Time when pulse started. */
  startTime: number;
  /** Duration in seconds (200-600ms). */
  duration: number;
  /** Channels this pulse affects and their target values. */
  channels: Partial<Record<Channel, number>>;
  /** Whether this pulse is additive (added to base) or overriding. */
  additive: boolean;
}

/** A gesture clip currently playing. */
export interface GestureClip {
  /** Animation name/id. */
  name: string;
  /** Bone mask: which bone groups the clip controls. */
  mask: "arms" | "upper_body" | "head" | "full_body";
  /** Start time of the clip. */
  startTime: number;
  /** Duration in seconds. */
  duration: number;
  /** Intensity 0-1. */
  intensity: number;
  /** Blend-in/out time in seconds. */
  blendTime: number;
  /** Per-channel keyframe data (simplified for now). */
  keyframes: Record<string, number[]>;
}

/** Output from a single layer: partial channel values. */
export type LayerOutput = Partial<Record<Channel, number>>;

/** Interface that all six layers must implement. */
export interface Layer {
  /** Unique layer name (idle, affect, cognitive, events, speech, gesture). */
  readonly name: LayerName;
  /** Groups this layer is allowed to write (per ownership table). */
  readonly groups: readonly ChannelGroup[];
  /**
   * Update the layer for one frame.
   * @param t Current time in seconds
   * @param dt Delta time in seconds
   * @param input Controller input for this frame
   * @returns Partial channel values this layer wants to write
   */
  update(t: number, dt: number, input: ControllerInput): LayerOutput;
  /** Reset layer state (e.g., after a gesture ends). */
  reset?(): void;
}

/** Names of the six layers in priority order (lowest to highest within a group). */
export type LayerName = "idle" | "affect" | "cognitive" | "events" | "speech" | "gesture";

/** All layer names in order. */
export const LAYER_NAMES: readonly LayerName[] = [
  "idle",
  "affect",
  "cognitive",
  "events",
  "speech",
  "gesture",
] as const;

/** Default controller config. */
export const DEFAULT_CONFIG: ControllerConfig = {
  noiseSeed: 42,
  breathingRate: 0.25, // ~4 second cycle
  weightShiftRate: 0.1, // ~10 second cycle
  blinkInterval: [2, 6],
  lookAtSmoothing: {
    eyes: 0.15,
    head: 0.3,
    chest: 0.5,
  },
  mood: null,
};