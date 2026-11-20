/**
 * Idle Life Layer (Layer 1): continuous procedural animation.
 * Breathing, weight shift, small spine and neck noise from a seeded noise function.
 */

import type { Layer, LayerOutput, ControllerInput, ControllerConfig } from "./layers";
import { CHANNELS_BY_GROUP, Channel } from "./channels";

/** Seeded pseudo-random number generator (Mulberry32). */
export class SeededRandom {
  public seed: number;

  constructor(seed: number) {
    this.seed = seed >>> 0;
  }

  /** Returns a random float in [0, 1). */
  next(): number {
    this.seed += 0x6d2b79f5;
    let t = Math.imul(this.seed ^ (this.seed >>> 15), 1 | this.seed);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  /** Returns a random float in [-1, 1). */
  nextSigned(): number {
    return this.next() * 2 - 1;
  }
}

/** 1D noise function using seeded random with interpolation. */
function seededNoise1D(random: SeededRandom, x: number): number {
  const i = Math.floor(x);
  const f = x - i;
  const a = random.nextSigned();
  // Re-seed for the next integer to get consistent values
  const nextRandom = new SeededRandom(random.seed + 1);
  const b = nextRandom.nextSigned();
  // Smooth interpolation
  const t = f * f * (3 - 2 * f);
  return a + (b - a) * t;
}

/** 2D noise for more organic movement. */
function seededNoise2D(random: SeededRandom, x: number, y: number): number {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;

  // Get four corner values
  const r00 = new SeededRandom(random.seed + ix * 10000 + iy).nextSigned();
  const r10 = new SeededRandom(random.seed + (ix + 1) * 10000 + iy).nextSigned();
  const r01 = new SeededRandom(random.seed + ix * 10000 + iy + 1).nextSigned();
  const r11 = new SeededRandom(random.seed + (ix + 1) * 10000 + iy + 1).nextSigned();

  // Bilinear interpolation with smoothstep
  const sx = fx * fx * (3 - 2 * fx);
  const sy = fy * fy * (3 - 2 * fy);

  const nx0 = r00 + (r10 - r00) * sx;
  const nx1 = r01 + (r11 - r01) * sx;
  return nx0 + (nx1 - nx0) * sy;
}

export class IdleLayer implements Layer {
  readonly name = "idle" as const;
  readonly groups = ["body", "head", "arms"] as const;

  private random: SeededRandom;
  private breathingPhase = 0;
  private weightShiftPhase = 0;
  private noiseOffsetX = 0;
  private noiseOffsetY = 0;

  constructor(config: ControllerConfig) {
    this.random = new SeededRandom(config.noiseSeed + 1000); // Offset seed for idle layer
    // Initialize noise offsets with random values
    this.noiseOffsetX = this.random.next() * 1000;
    this.noiseOffsetY = this.random.next() * 1000;
  }

  update(t: number, dt: number, input: ControllerInput): LayerOutput {
    const output: LayerOutput = {};

    // Breathing cycle (spine, chest, neck subtle movement)
    const breathingRate = input.config.breathingRate ?? 0.25;
    this.breathingPhase += dt * breathingRate * 2 * Math.PI;
    const breath = Math.sin(this.breathingPhase) * 0.15; // Amplitude ~0.15
    const breathInhale = Math.max(0, breath); // Only on inhale for chest expansion

    output.spine = breath * 0.5;
    output.chest = breathInhale * 0.8;
    output.neck = breath * 0.3;

    // Weight shift (slow side-to-side movement)
    const weightShiftRate = input.config.weightShiftRate ?? 0.1;
    this.weightShiftPhase += dt * weightShiftRate * 2 * Math.PI;
    const weightShift = Math.sin(this.weightShiftPhase) * 0.08;

    output.spine += weightShift * 0.3;
    output.chest += weightShift * 0.2;
    output.neck += weightShift * 0.1;
    output.shoulderL = -weightShift * 0.15;
    output.shoulderR = weightShift * 0.15;

    // Small spine and neck noise (seeded, deterministic)
    const noiseFreq = 0.5; // cycles per second
    const noiseAmp = 0.02;
    const noiseX = this.noiseOffsetX + t * noiseFreq;
    const noiseY = this.noiseOffsetY + t * noiseFreq * 0.7;

    output.spine += seededNoise2D(this.random, noiseX, noiseY) * noiseAmp;
    output.chest += seededNoise2D(this.random, noiseX + 100, noiseY + 100) * noiseAmp;
    output.neck += seededNoise2D(this.random, noiseX + 200, noiseY + 200) * noiseAmp * 0.5;

    // Hand settle (very subtle)
    const handNoise = seededNoise1D(this.random, t * 0.3) * 0.01;
    output.handL = handNoise;
    output.handR = -handNoise;

    // Ensure we only output channels in our groups
    return this.filterOutput(output);
  }

  reset(): void {
    this.breathingPhase = 0;
    this.weightShiftPhase = 0;
  }

  /** Filter output to only include channels this layer owns. */
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