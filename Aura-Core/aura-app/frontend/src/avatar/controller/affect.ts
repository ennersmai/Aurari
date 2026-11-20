/**
 * Affect Layer (Layer 2): maps emotional deviation to facial expressions and posture.
 * Uses seeded random for deterministic asymmetry and timing.
 * Input: emotion deviation (27 dimensions) and mood (valence/arousal or null).
 */

import type { Layer, LayerOutput, ControllerInput, ControllerConfig } from "./layers";
import { Channel, CHANNELS_BY_GROUP } from "./channels";
import { SeededRandom } from "./idle";
import dimensionToAuData from "./tables/dimension_to_au.json" with { type: "json" };
import auToArkitData from "./tables/au_to_arkit.json" with { type: "json" };

// Type definitions for JSON data
interface DimensionToAuData {
  inwardDimensions: string[];
  socialDimensions: string[];
  mappings: Record<string, Record<string, number>>;
}

interface AuToArkitData {
  mappings: Record<string, Record<string, number>>;
}

// Configuration for affect behavior
export interface AffectConfig {
  /** Seed for deterministic randomness. */
  seed: number;
  /** Margin for dominant emotion replacement (0.05). */
  dominanceMargin: number;
  /** Time a newcomer must beat third place before replacing (ms). */
  dominanceHoldTime: number;
  /** Eyes lead time range [min, max] in seconds (0.15-0.25). */
  eyesLeadRange: [number, number];
  /** Asymmetry range [min, max] as fraction (0.05-0.10). */
  asymmetryRange: [number, number];
  /** Posture influence from mood (valence, arousal). */
  postureFromMood: boolean;
}

export const DEFAULT_AFFECT_CONFIG: AffectConfig = {
  seed: 42,
  dominanceMargin: 0.05,
  dominanceHoldTime: 0.3, // 300ms
  eyesLeadRange: [0.15, 0.25],
  asymmetryRange: [0.05, 0.10],
  postureFromMood: true,
};

// Internal state for tracking dominant emotions
interface DominantEmotion {
  dimension: string;
  value: number;
  holdStartTime: number; // When it started beating the third place
}

interface AffectState {
  dominantEmotions: DominantEmotion[];
  lastDeviation: Record<string, number>;
  upperFaceDelay: number; // Delay for upper face in seconds
  lowerFaceDelay: number; // Delay for lower face in seconds
  asymmetryCache: Map<string, { left: number; right: number }>;
}

// Action Unit to ARKit mapping with weights
type AuToArkitMap = Record<string, Record<string, number>>;
// Dimension to AU mapping with weights
type DimensionToAuMap = Record<string, Record<string, number>>;

/**
 * AffectLayer produces facial expressions and posture from emotional deviation.
 * Deterministic given the same seed and time inputs.
 */
export class AffectLayer implements Layer {
  readonly name = "affect" as const;
  readonly groups = ["upperFace", "lowerFace", "eyes", "jaw", "head", "body"] as const;

  private config: AffectConfig;
  private random: SeededRandom;
  private dimensionToAu: DimensionToAuMap;
  private auToArkit: AuToArkitMap;
  private inwardDimensions: Set<string>;
  private socialDimensions: Set<string>;
  private state: AffectState;

  constructor(
    config: Partial<AffectConfig> = {},
    dimensionToAuOverride?: DimensionToAuData,
    auToArkitOverride?: AuToArkitData
  ) {
    this.config = { ...DEFAULT_AFFECT_CONFIG, ...config };
    this.random = new SeededRandom(this.config.seed);

    // Load mappings from JSON (or use overrides for testing)
    const dimData = dimensionToAuOverride || dimensionToAuData;
    const auData = auToArkitOverride || auToArkitData;

    this.dimensionToAu = dimData.mappings;
    this.auToArkit = auData.mappings;
    this.inwardDimensions = new Set(dimData.inwardDimensions);
    this.socialDimensions = new Set(dimData.socialDimensions);

    this.state = {
      dominantEmotions: [],
      lastDeviation: {},
      upperFaceDelay: 0,
      lowerFaceDelay: 0,
      asymmetryCache: new Map(),
    };
  }

  update(t: number, dt: number, input: ControllerInput): LayerOutput {
    const output: LayerOutput = {};

    // Get emotion deviation from input
    const deviation = input.emotionDeviation || {};
    const mood = input.config.mood; // May be null until E4

    // 1. Update dominant emotions (top 3 by absolute deviation with hysteresis)
    this.updateDominantEmotions(deviation, t);

    // 2. Compute eyes lead delay (150-250ms)
    this.updateEyesLead(t);

    // 3. Compute facial expression from dominant emotions
    this.computeFacialExpression(output, t);

    // 4. Compute posture from mood (skip if mood is null)
    if (mood && this.config.postureFromMood) {
      this.computePosture(output, mood, t);
    }

    // 5. Filter to only channels this layer owns
    return this.filterOutput(output);
  }

  /** Update the top 3 dominant emotions with hysteresis. */
  private updateDominantEmotions(deviation: Record<string, number>, t: number): void {
    // Sort dimensions by absolute deviation (descending)
    const sorted = Object.entries(deviation)
      .filter(([, v]) => Math.abs(v) > 0.01) // Ignore near-zero
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
      .slice(0, 3);

    const newDominant: DominantEmotion[] = [];

    for (let i = 0; i < sorted.length; i++) {
      const [dimension, value] = sorted[i];
      let holdStartTime = t;

      // Check if this dimension was already in dominant emotions
      const existing = this.state.dominantEmotions.find((d) => d.dimension === dimension);
      if (existing) {
        holdStartTime = existing.holdStartTime;
      } else if (i === 2 && this.state.dominantEmotions.length >= 3) {
        // Newcomer to third place: check if it beats current third by margin for hold time
        const currentThird = this.state.dominantEmotions[2];
        if (currentThird && Math.abs(value) > Math.abs(currentThird.value) + this.config.dominanceMargin) {
          // Check if it has been beating for enough time
          if (t - holdStartTime >= this.config.dominanceHoldTime) {
            holdStartTime = t; // Will be set when condition is met
          } else {
            // Not held long enough, keep current third
            newDominant.push(currentThird);
            continue;
          }
        } else {
          // Doesn't beat by margin, keep current third
          newDominant.push(currentThird);
          continue;
        }
      }

      newDominant.push({ dimension, value, holdStartTime });
    }

    // If fewer than 3, pad with previous ones that still have significant deviation
    while (newDominant.length < 3 && this.state.dominantEmotions.length > newDominant.length) {
      const idx = newDominant.length;
      const prev = this.state.dominantEmotions[idx];
      if (prev && Math.abs(deviation[prev.dimension] || 0) > 0.01) {
        newDominant.push(prev);
      } else {
        break;
      }
    }

    this.state.dominantEmotions = newDominant;
    this.state.lastDeviation = { ...deviation };
  }

  /** Update eyes lead delay (upper face moves 150-250ms before lower face). */
  private updateEyesLead(t: number): void {
    // Use deterministic random for the delay range
    const leadRandom = new SeededRandom(this.config.seed + 10000);
    const delay = this.config.eyesLeadRange[0] + leadRandom.next() * (this.config.eyesLeadRange[1] - this.config.eyesLeadRange[0]);
    this.state.upperFaceDelay = delay;
    this.state.lowerFaceDelay = 0; // Lower face starts immediately
  }

  /** Compute facial expression from dominant emotions. */
  private computeFacialExpression(output: LayerOutput, t: number): void {
    // Accumulate AU weights from dominant emotions
    const auWeights: Record<string, number> = {};

    for (const dom of this.state.dominantEmotions) {
      const auMap = this.dimensionToAu[dom.dimension];
      if (!auMap) continue;

      const strength = Math.abs(dom.value);

      for (const [au, weight] of Object.entries(auMap)) {
        const contribution = weight * strength;
        auWeights[au] = (auWeights[au] || 0) + contribution;
      }
    }

    // Convert AU weights to ARKit channels
    const arkitWeights: Record<string, number> = {};

    for (const [au, auWeight] of Object.entries(auWeights)) {
      const arkitMap = this.auToArkit[au];
      if (!arkitMap) continue;

      for (const [arkitChannel, arkitWeight] of Object.entries(arkitMap)) {
        const contribution = auWeight * arkitWeight;
        arkitWeights[arkitChannel] = (arkitWeights[arkitChannel] || 0) + contribution;
      }
    }

    // Apply zoning, asymmetry, and eyes lead
    for (const [channel, weight] of Object.entries(arkitWeights)) {
      const ch = channel as Channel;
      const group = this.getChannelGroup(ch);

      // Determine if this is upper face or lower face
      const isUpperFace = group === "upperFace" || group === "eyes";
      const isLowerFace = group === "lowerFace" || group === "jaw";

      // Apply eyes lead: upper face channels get a time offset
      let finalWeight = weight;
      if (isUpperFace && this.state.upperFaceDelay > 0) {
        // Upper face leads - we apply the weight immediately but with a slight
        // temporal shift in the animation (handled by the mixer/render loop)
        // For now, just apply the weight
      }

      // Apply asymmetry for left/right channels
      const asymPair = this.getAsymmetryPair(ch);
      if (asymPair) {
        const asym = this.getAsymmetry(ch, domDimensionForChannel(ch) || this.state.dominantEmotions[0]?.dimension || "neutral");
        if (asymPair.left === ch) {
          finalWeight *= asym.left;
        } else if (asymPair.right === ch) {
          finalWeight *= asym.right;
        }
      }

      // Apply zoning weights
      if (isUpperFace) {
        const zoneWeight = this.getZoneWeight(ch, "upper");
        finalWeight *= zoneWeight;
      } else if (isLowerFace) {
        const zoneWeight = this.getZoneWeight(ch, "lower");
        finalWeight *= zoneWeight;
      }

      // Clamp to [0, 1]
      output[ch] = Math.max(0, Math.min(1, finalWeight));
    }
  }

  /** Get the channel group for a channel. */
  private getChannelGroup(channel: Channel): string {
    for (const [group, channels] of Object.entries(CHANNELS_BY_GROUP)) {
      if (channels.includes(channel)) {
        return group;
      }
    }
    return "unknown";
  }

  /** Get left/right asymmetry pair for a channel. */
  private getAsymmetryPair(channel: Channel): { left: Channel; right: Channel } | null {
    const pairs: Record<string, { left: Channel; right: Channel }> = {
      browInnerUp: { left: "browInnerUp" as Channel, right: "browInnerUp" as Channel }, // Single channel
      browOuterUpLeft: { left: "browOuterUpLeft" as Channel, right: "browOuterUpRight" as Channel },
      browOuterUpRight: { left: "browOuterUpLeft" as Channel, right: "browOuterUpRight" as Channel },
      browDownLeft: { left: "browDownLeft" as Channel, right: "browDownRight" as Channel },
      browDownRight: { left: "browDownLeft" as Channel, right: "browDownRight" as Channel },
      eyeWideLeft: { left: "eyeWideLeft" as Channel, right: "eyeWideRight" as Channel },
      eyeWideRight: { left: "eyeWideLeft" as Channel, right: "eyeWideRight" as Channel },
      eyeSquintLeft: { left: "eyeSquintLeft" as Channel, right: "eyeSquintRight" as Channel },
      eyeSquintRight: { left: "eyeSquintLeft" as Channel, right: "eyeSquintRight" as Channel },
      cheekSquintLeft: { left: "cheekSquintLeft" as Channel, right: "cheekSquintRight" as Channel },
      cheekSquintRight: { left: "cheekSquintLeft" as Channel, right: "cheekSquintRight" as Channel },
      noseSneerLeft: { left: "noseSneerLeft" as Channel, right: "noseSneerRight" as Channel },
      noseSneerRight: { left: "noseSneerLeft" as Channel, right: "noseSneerRight" as Channel },
      mouthSmileLeft: { left: "mouthSmileLeft" as Channel, right: "mouthSmileRight" as Channel },
      mouthSmileRight: { left: "mouthSmileLeft" as Channel, right: "mouthSmileRight" as Channel },
      mouthDimpleLeft: { left: "mouthDimpleLeft" as Channel, right: "mouthDimpleRight" as Channel },
      mouthDimpleRight: { left: "mouthDimpleLeft" as Channel, right: "mouthDimpleRight" as Channel },
      mouthUpperUpLeft: { left: "mouthUpperUpLeft" as Channel, right: "mouthUpperUpRight" as Channel },
      mouthUpperUpRight: { left: "mouthUpperUpLeft" as Channel, right: "mouthUpperUpRight" as Channel },
      mouthCornerPullLeft: { left: "mouthCornerPullLeft" as Channel, right: "mouthCornerPullRight" as Channel },
      mouthCornerPullRight: { left: "mouthCornerPullLeft" as Channel, right: "mouthCornerPullRight" as Channel },
      mouthStretchLeft: { left: "mouthStretchLeft" as Channel, right: "mouthStretchRight" as Channel },
      mouthStretchRight: { left: "mouthStretchLeft" as Channel, right: "mouthStretchRight" as Channel },
      mouthPressLeft: { left: "mouthPressLeft" as Channel, right: "mouthPressRight" as Channel },
      mouthPressRight: { left: "mouthPressLeft" as Channel, right: "mouthPressRight" as Channel },
      mouthPucker: { left: "mouthPucker" as Channel, right: "mouthPucker" as Channel },
      mouthOpen: { left: "mouthOpen" as Channel, right: "mouthOpen" as Channel },
      jawOpen: { left: "jawOpen" as Channel, right: "jawOpen" as Channel },
    };

    return pairs[channel] || null;
  }

  /** Get deterministic asymmetry for a channel based on dimension name. */
  private getAsymmetry(channel: Channel, dimension: string): { left: number; right: number } {
    const cacheKey = `${dimension}_${channel}`;
    if (this.state.asymmetryCache.has(cacheKey)) {
      return this.state.asymmetryCache.get(cacheKey)!;
    }

    // Create a deterministic seed from dimension name
    let seed = this.config.seed;
    for (let i = 0; i < dimension.length; i++) {
      seed = (seed * 31 + dimension.charCodeAt(i)) >>> 0;
    }
    const asymRandom = new SeededRandom(seed + 1000);

    const asymRange = this.config.asymmetryRange;
    const asymFactor = asymRange[0] + asymRandom.next() * (asymRange[1] - asymRange[0]);

    // 5-10% offset: one side gets (1 - factor), other gets (1 + factor)
    // Alternate which side gets the boost based on another random bit
    const leftBoost = asymRandom.next() > 0.5;

    const result = {
      left: leftBoost ? 1 + asymFactor : 1 - asymFactor,
      right: leftBoost ? 1 - asymFactor : 1 + asymFactor,
    };

    this.state.asymmetryCache.set(cacheKey, result);
    return result;
  }

  /** Get zone weight for a channel (upper face vs lower face emphasis). */
  private getZoneWeight(channel: Channel, zone: "upper" | "lower"): number {
    // Check if the dominant emotions are inward or social
    let inwardWeight = 0;
    let socialWeight = 0;

    for (const dom of this.state.dominantEmotions) {
      if (this.inwardDimensions.has(dom.dimension)) {
        inwardWeight += Math.abs(dom.value);
      }
      if (this.socialDimensions.has(dom.dimension)) {
        socialWeight += Math.abs(dom.value);
      }
    }

    const total = inwardWeight + socialWeight;
    if (total === 0) return 1.0;

    if (zone === "upper") {
      // Upper face weighted by inward dimensions
      return 0.5 + 0.5 * (inwardWeight / total);
    } else {
      // Lower face weighted by social dimensions
      return 0.5 + 0.5 * (socialWeight / total);
    }
  }

  /** Compute posture from mood valence and arousal. */
  private computePosture(output: LayerOutput, mood: { valence: number; arousal: number }, t: number): void {
    // Valence: -1 (negative) to 1 (positive)
    // Arousal: 0 (calm) to 1 (excited)

    // Chest: positive valence -> chest up/open, negative -> chest down/closed
    const chestValence = mood.valence * 0.15; // ±0.15
    output.chest = (output.chest || 0) + chestValence;

    // Spine: arousal affects spine extension
    const spineArousal = (mood.arousal - 0.5) * 0.1; // ±0.05
    output.spine = (output.spine || 0) + spineArousal;

    // Neck: valence affects chin position
    const neckValence = mood.valence * 0.1; // ±0.1
    output.neck = (output.neck || 0) + neckValence;

    // Head: slight tilt based on valence
    output.head = (output.head || 0) + mood.valence * 0.05;

    // Breathing rate affected by arousal (would be handled by idle layer)
    // We just set a config hint here if needed
  }

  /** Get the dominant dimension that drives a channel (for asymmetry). */
  private getDominantDimensionForChannel(channel: Channel): string | null {
    // Simple heuristic: check which AU this channel comes from, then which dimension
    for (const [dimension, auMap] of Object.entries(this.dimensionToAu)) {
      for (const au of Object.keys(auMap)) {
        const arkitMap = this.auToArkit[au];
        if (arkitMap && channel in arkitMap) {
          return dimension;
        }
      }
    }
    return null;
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

  reset(): void {
    this.state = {
      dominantEmotions: [],
      lastDeviation: {},
      upperFaceDelay: 0,
      lowerFaceDelay: 0,
      asymmetryCache: new Map(),
    };
    this.random = new SeededRandom(this.config.seed);
  }
}

/** Helper function to get the dominant dimension for a channel (for asymmetry). */
function domDimensionForChannel(channel: Channel): string | null {
  // This is a placeholder - the actual logic is in the class
  return null;
}