/**
 * Blink Generator: blinks every 2 to 6 seconds, also on large gaze shifts.
 * This is a standalone system (not a layer) that the events layer uses.
 * Deterministic: no Date.now() or Math.random() - uses seeded random and passed-in time.
 */

import type { ControllerInput } from "./layers";
import { Channel } from "./channels";
import { SeededRandom } from "./idle";

/** Blink state machine states. */
type BlinkState = "idle" | "closing" | "closed" | "opening";

/** Configuration for blink behavior. */
export interface BlinkConfig {
  /** Minimum interval between blinks (seconds). */
  minInterval: number;
  /** Maximum interval between blinks (seconds). */
  maxInterval: number;
  /** Blink duration (seconds). */
  blinkDuration: number;
  /** Gaze shift threshold in radians to trigger a blink. */
  gazeShiftThreshold: number;
  /** Seed for deterministic randomness. */
  seed: number;
}

/** Default blink configuration. */
export const DEFAULT_BLINK_CONFIG: BlinkConfig = {
  minInterval: 2,
  maxInterval: 6,
  blinkDuration: 0.15,
  gazeShiftThreshold: 0.5,
  seed: 12345,
};

/** Result of a blink update. */
export interface BlinkResult {
  /** Current blink intensity for left eye (0-1). */
  left: number;
  /** Current blink intensity for right eye (0-1). */
  right: number;
  /** Whether a blink is currently in progress. */
  isBlinking: boolean;
  /** Time until next scheduled blink (seconds). */
  timeToNextBlink: number;
}

/**
 * BlinkGenerator produces blink curves for left/right eyes.
 * Deterministic given the same seed and time inputs.
 */
export class BlinkGenerator {
  private random: SeededRandom;
  private config: BlinkConfig;
  private nextBlinkTime: number;
  private state: BlinkState = "idle";
  private stateStartTime: number = 0;
  private currentIntensity: number = 0;
  private lastGazeDirection: { x: number; y: number; z: number } = { x: 0, y: 0, z: -1 };

  constructor(config: BlinkConfig = DEFAULT_BLINK_CONFIG) {
    this.config = config;
    this.random = new SeededRandom(config.seed);
    this.nextBlinkTime = this.random.next() * (config.maxInterval - config.minInterval) + config.minInterval;
  }

  /**
   * Update the blink generator for one frame.
   * @param t Current time in seconds (monotonic)
   * @param dt Delta time in seconds
   * @param input Controller input (for gaze target)
   * @returns Blink intensities for left and right eyes
   */
  update(t: number, dt: number, input: ControllerInput): BlinkResult {
    // Check for large gaze shift
    if (input.gazeTarget) {
      const gazeDir = this.normalize(input.gazeTarget);
      const angle = this.angleBetween(this.lastGazeDirection, gazeDir);

      if (angle > this.config.gazeShiftThreshold && this.state === "idle") {
        this.triggerBlink(t);
      }
      this.lastGazeDirection = gazeDir;
    }

    // Automatic blink timer
    if (this.state === "idle" && t >= this.nextBlinkTime) {
      this.triggerBlink(t);
    }

    // Update blink animation state machine
    this.updateBlinkState(t);

    // Calculate time to next blink
    const timeToNextBlink = this.state === "idle" ? Math.max(0, this.nextBlinkTime - t) : 0;

    return {
      left: this.currentIntensity * this.getEyeAsymmetry("left"),
      right: this.currentIntensity * this.getEyeAsymmetry("right"),
      isBlinking: this.state !== "idle",
      timeToNextBlink,
    };
  }

  /** Trigger a blink at the given time. */
  triggerBlink(t: number): void {
    this.state = "closing";
    this.stateStartTime = t;
    this.currentIntensity = 0;
    // Deterministic blink duration with slight variation
    this.config.blinkDuration = 0.1 + this.random.next() * 0.1;
  }

  /** Force a blink (for testing or external events). */
  forceBlink(t: number): void {
    if (this.state === "idle") {
      this.triggerBlink(t);
    }
  }

  /** Reset to initial state (for testing). */
  reset(t: number = 0): void {
    this.state = "idle";
    this.stateStartTime = 0;
    this.currentIntensity = 0;
    this.random = new SeededRandom(this.config.seed);
    this.nextBlinkTime = t + this.random.next() * (this.config.maxInterval - this.config.minInterval) + this.config.minInterval;
    this.lastGazeDirection = { x: 0, y: 0, z: -1 };
  }

  /** Get the current blink state. */
  getState(): BlinkState {
    return this.state;
  }

  private updateBlinkState(t: number): void {
    const elapsed = t - this.stateStartTime;
    const halfDur = this.config.blinkDuration / 2;

    switch (this.state) {
      case "closing":
        this.currentIntensity = Math.min(1, elapsed / halfDur);
        if (elapsed >= halfDur) {
          this.state = "closed";
          this.stateStartTime = t;
        }
        break;
      case "closed":
        this.currentIntensity = 1.0;
        if (elapsed >= halfDur * 0.3) { // Brief hold
          this.state = "opening";
          this.stateStartTime = t;
        }
        break;
      case "opening":
        this.currentIntensity = Math.max(0, 1 - elapsed / halfDur);
        if (elapsed >= halfDur) {
          this.state = "idle";
          this.currentIntensity = 0;
          this.scheduleNextBlink(t);
        }
        break;
      case "idle":
        this.currentIntensity = 0;
        break;
    }
  }

  private scheduleNextBlink(t: number): void {
    const interval = this.config.minInterval + this.random.next() * (this.config.maxInterval - this.config.minInterval);
    this.nextBlinkTime = t + interval;
  }

  /** Get deterministic asymmetry factor for left/right eye. */
  private getEyeAsymmetry(eye: "left" | "right"): number {
    // Deterministic asymmetry based on seed
    const asymRandom = new SeededRandom(this.config.seed + (eye === "left" ? 100 : 200));
    return 0.95 + asymRandom.next() * 0.1; // 0.95 to 1.05
  }

  private normalize(v: { x: number; y: number; z: number }): { x: number; y: number; z: number } {
    const len = Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
    if (len === 0) return { x: 0, y: 0, z: -1 };
    return { x: v.x / len, y: v.y / len, z: v.z / len };
  }

  private angleBetween(a: { x: number; y: number; z: number }, b: { x: number; y: number; z: number }): number {
    const dot = Math.max(-1, Math.min(1, a.x * b.x + a.y * b.y + a.z * b.z));
    return Math.acos(dot);
  }
}