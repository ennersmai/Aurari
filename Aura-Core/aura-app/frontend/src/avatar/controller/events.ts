/**
 * Events Layer (Layer 4): short additive pulses (200-600ms) that return to exactly zero.
 * Includes surprise, amusement, nod pulses. Uses BlinkGenerator for blinks.
 * Deterministic: uses seeded random for pulse durations.
 */

import type { Layer, LayerOutput, ControllerInput, EventPulse } from "./layers";
import { Channel, CHANNELS_BY_GROUP } from "./channels";
import { BlinkGenerator, BlinkConfig, DEFAULT_BLINK_CONFIG } from "./blink";
import { SeededRandom } from "./idle";

/** Configuration for event pulses. */
export interface EventsConfig {
  /** Blink configuration. */
  blink: BlinkConfig;
  /** Default pulse duration range [min, max] in seconds. */
  pulseDurationRange: [number, number];
  /** Seed for deterministic randomness. */
  seed: number;
}

/** Default events configuration. */
export const DEFAULT_EVENTS_CONFIG: EventsConfig = {
  blink: DEFAULT_BLINK_CONFIG,
  pulseDurationRange: [0.2, 0.6],
  seed: 12345,
};

/** Active event pulse with computed curve. */
interface ActivePulse {
  pulse: EventPulse;
  startTime: number;
  endTime: number;
}

/**
 * EventsLayer produces short additive pulses for expressions like surprise, amusement, nods.
 * Pulses return to exactly zero after their duration.
 * Deterministic given the same seed and time inputs.
 */
export class EventsLayer implements Layer {
  readonly name = "events" as const;
  readonly groups = ["upperFace", "lowerFace", "eyes", "jaw", "head", "body"] as const;

  private config: EventsConfig;
  private blinkGenerator: BlinkGenerator;
  private activePulses: ActivePulse[] = [];
  private pulseIdCounter = 0;
  private random: SeededRandom;

  constructor(config: EventsConfig = DEFAULT_EVENTS_CONFIG) {
    this.config = config;
    this.blinkGenerator = new BlinkGenerator(config.blink);
    this.random = new SeededRandom(config.seed);
  }

  update(t: number, dt: number, input: ControllerInput): LayerOutput {
    const output: LayerOutput = {};

    // Update blink generator and add blink channels
    const blinkResult = this.blinkGenerator.update(t, dt, input);
    if (blinkResult.isBlinking || blinkResult.left > 0 || blinkResult.right > 0) {
      output.eyeBlinkLeft = blinkResult.left;
      output.eyeBlinkRight = blinkResult.right;
      output.eyeL = -blinkResult.left * 0.1;
      output.eyeR = -blinkResult.right * 0.1;
    }

    // Add new pulses from input
    for (const pulse of input.eventPulses) {
      this.addPulse(pulse, t);
    }

    // Update active pulses and add their contributions
    this.updatePulses(t, output);

    // Filter to only channels this layer owns
    return this.filterOutput(output);
  }

  /** Add a new event pulse. */
  addPulse(pulse: EventPulse, currentTime: number): void {
    const duration = pulse.duration ?? 
      (this.config.pulseDurationRange[0] + this.random.next() * (this.config.pulseDurationRange[1] - this.config.pulseDurationRange[0]));
    this.activePulses.push({
      pulse: { ...pulse, duration },
      startTime: currentTime,
      endTime: currentTime + duration,
    });
  }

  /** Trigger a surprise pulse (brows up, lids wide). */
  triggerSurprise(strength: number, currentTime: number): void {
    this.addPulse({
      id: `surprise_${this.pulseIdCounter++}`,
      type: "surprise",
      strength,
      startTime: currentTime,
      duration: 0.3 + this.random.next() * 0.2, // 300-500ms
      channels: {
        browInnerUp: strength * 0.8,
        browOuterUpLeft: strength * 0.6,
        browOuterUpRight: strength * 0.6,
        eyeWideLeft: strength * 0.7,
        eyeWideRight: strength * 0.7,
        eyeBlinkLeft: -0.5, // Suppress blink during surprise
        eyeBlinkRight: -0.5,
        jawOpen: strength * 0.3,
      },
      additive: true,
    }, currentTime);
  }

  /** Trigger an amusement pulse (smile, eye crinkle). */
  triggerAmusement(strength: number, currentTime: number): void {
    this.addPulse({
      id: `amusement_${this.pulseIdCounter++}`,
      type: "amusement",
      strength,
      startTime: currentTime,
      duration: 0.4 + this.random.next() * 0.2, // 400-600ms
      channels: {
        mouthSmileLeft: strength * 0.8,
        mouthSmileRight: strength * 0.8,
        cheekSquintLeft: strength * 0.5,
        cheekSquintRight: strength * 0.5,
        eyeSquintLeft: strength * 0.4,
        eyeSquintRight: strength * 0.4,
      },
      additive: true,
    }, currentTime);
  }

  /** Trigger a nod pulse (head up/down). */
  triggerNod(strength: number, currentTime: number): void {
    this.addPulse({
      id: `nod_${this.pulseIdCounter++}`,
      type: "nod",
      strength,
      startTime: currentTime,
      duration: 0.3 + this.random.next() * 0.15, // 300-450ms
      channels: {
        head: -strength * 0.3, // Head down
        neck: -strength * 0.2,
      },
      additive: true,
    }, currentTime);
  }

  /** Trigger a custom pulse. */
  triggerCustom(channels: Partial<Record<Channel, number>>, duration: number, currentTime: number): void {
    this.addPulse({
      id: `custom_${this.pulseIdCounter++}`,
      type: "custom",
      strength: 1,
      startTime: currentTime,
      duration,
      channels,
      additive: true,
    }, currentTime);
  }

  private updatePulses(t: number, output: LayerOutput): void {
    const remaining: ActivePulse[] = [];

    for (const active of this.activePulses) {
      const elapsed = t - active.startTime;
      const progress = elapsed / active.pulse.duration;

      if (progress >= 1) {
        // Pulse finished - ensure channels return to exactly zero
        // (handled by not adding them to output)
        continue;
      }

      // Compute pulse curve: smooth attack and decay
      const curve = this.pulseCurve(progress);

      // Add pulse contribution to output
      for (const [channel, value] of Object.entries(active.pulse.channels)) {
        if (value === undefined) continue;
        const ch = channel as Channel;
        const contribution = value * curve * active.pulse.strength;
        if (output[ch] !== undefined) {
          output[ch] += contribution;
        } else {
          output[ch] = contribution;
        }
      }

      remaining.push(active);
    }

    this.activePulses = remaining;
  }

  /** Pulse curve: smooth attack (0-0.3) and decay (0.3-1.0), returns exactly 0 at progress=1. */
  private pulseCurve(progress: number): number {
    if (progress <= 0) return 0;
    if (progress >= 1) return 0;
    
    // Smooth attack to peak at 30%, then decay
    if (progress < 0.3) {
      // Attack: ease out
      const t = progress / 0.3;
      return t * t * (3 - 2 * t); // Smoothstep
    } else {
      // Decay: ease in to zero
      const t = (progress - 0.3) / 0.7;
      return (1 - t) * (1 - t) * (3 - 2 * (1 - t)); // Inverted smoothstep
    }
  }

  /** Get the blink generator (for testing). */
  getBlinkGenerator(): BlinkGenerator {
    return this.blinkGenerator;
  }

  /** Clear all active pulses. */
  clearPulses(): void {
    this.activePulses = [];
  }

  reset(): void {
    this.activePulses = [];
    this.blinkGenerator.reset();
    this.random = new SeededRandom(this.config.seed);
    this.pulseIdCounter = 0;
  }

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
}