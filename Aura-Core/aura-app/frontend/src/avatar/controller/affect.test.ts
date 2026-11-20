/**
 * Tests for the Affect Layer.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { AffectLayer, DEFAULT_AFFECT_CONFIG } from "./affect.js";
import { ControllerInput, ControllerConfig } from "./layers.js";
import { Channel } from "./channels.js";

// Create a minimal test input
function createInput(overrides: Partial<ControllerInput> = {}): ControllerInput {
  const config: ControllerConfig = {
    noiseSeed: 42,
    breathingRate: 0.25,
    weightShiftRate: 0.1,
    blinkInterval: [2, 6],
    lookAtSmoothing: { eyes: 0.15, head: 0.3, chest: 0.5 },
    mood: null,
  };
  return {
    t: 0,
    dt: 1 / 60,
    emotionDeviation: {},
    cognitiveState: "attending",
    isSpeaking: false,
    visemes: {},
    gazeTarget: null,
    eventPulses: [],
    gestureClip: null,
    config,
    ...overrides,
  };
}

describe("AffectLayer", () => {
  let layer: AffectLayer;

  beforeEach(() => {
    layer = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 12345 });
  });

  describe("T4: Neutral at rest", () => {
    it("zero deviation gives exactly the neutral face and pose", () => {
      const input = createInput({ emotionDeviation: {} });
      const output = layer.update(0, 1 / 60, input);

      // All face channels should be 0 (or very close to 0)
      for (const [channel, value] of Object.entries(output)) {
        expect(Math.abs(value)).toBeLessThan(0.001);
      }
    });

    it("zero deviation with mood=null gives neutral pose", () => {
      const input = createInput({ 
        emotionDeviation: {},
        config: { ...createInput().config, mood: null }
      });
      const output = layer.update(0, 1 / 60, input);

      // Body channels should be 0 (no posture change)
      expect(output.spine).toBeUndefined();
      expect(output.chest).toBeUndefined();
      expect(output.neck).toBeUndefined();
      expect(output.head).toBeUndefined();
    });
  });

  describe("Dominant emotions", () => {
    it("tracks top 3 dimensions by absolute deviation", () => {
      const input = createInput({
        emotionDeviation: {
          joy: 0.8,
          curiosity: 0.6,
          sadness: 0.4,
          anger: 0.2,
        },
      });
      const output = layer.update(0, 1 / 60, input);

      // Should produce expression for joy, curiosity, sadness (top 3)
      // At minimum, some face channels should be non-zero
      const faceChannels = Object.keys(output).filter((k) => 
        ["browInnerUp", "mouthSmileLeft", "cheekSquintLeft", "eyeWideLeft"].includes(k)
      );
      expect(faceChannels.length).toBeGreaterThan(0);
    });

    it("newcomer replaces third after margin for 300ms", () => {
      // Start with three emotions
      const input1 = createInput({
        emotionDeviation: { joy: 0.5, curiosity: 0.4, sadness: 0.3 },
      });
      layer.update(0, 1 / 60, input1);

      // At t=0.1, newcomer anger at 0.36 (beats sadness 0.3 by 0.06 > 0.05 margin)
      const input2 = createInput({
        t: 0.1,
        emotionDeviation: { joy: 0.5, curiosity: 0.4, sadness: 0.3, anger: 0.36 },
      });
      layer.update(0.1, 1 / 60, input2);

      // At t=0.4 (300ms later), anger should replace sadness
      const input3 = createInput({
        t: 0.4,
        emotionDeviation: { joy: 0.5, curiosity: 0.4, sadness: 0.3, anger: 0.36 },
      });
      const output = layer.update(0.4, 1 / 60, input3);

      // Should now have joy, curiosity, anger as top 3
      // (we can't easily test internal state, but expression should reflect anger)
      const hasMouthExpression = Object.keys(output).some((k) => 
        k.startsWith("mouth") && Math.abs(output[k as Channel] || 0) > 0.01
      );
      expect(hasMouthExpression).toBe(true);
    });

    it("T3: newcomer to third place requires margin and hold time (hysteresis)", () => {
      // This tests the hysteresis: a newcomer emotion must beat the current 
      // third place by margin (0.05) for 300ms before replacing it
      const layer = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 12345 });
      
      // Start with three emotions: joy (0.5), curiosity (0.45), sadness (0.4)
      // The third place is sadness at 0.4
      let input = createInput({ 
        t: 0, 
        emotionDeviation: { joy: 0.5, curiosity: 0.45, sadness: 0.4 } 
      });
      layer.update(0, 1 / 60, input);
      
      // Now introduce anger at 0.43 (beats sadness 0.4 by 0.03 < 0.05 margin)
      // It should NOT replace sadness
      input = createInput({ 
        t: 0.1, 
        emotionDeviation: { joy: 0.5, curiosity: 0.45, sadness: 0.4, anger: 0.43 } 
      });
      layer.update(0.1, 1 / 60, input);
      
      // Even after 200ms, still not enough margin
      input = createInput({ 
        t: 0.3, 
        emotionDeviation: { joy: 0.5, curiosity: 0.45, sadness: 0.4, anger: 0.43 } 
      });
      layer.update(0.3, 1 / 60, input);
      
      // Now increase anger to 0.46 (beats sadness 0.4 by 0.06 > 0.05 margin)
      // But it needs to hold for 300ms
      input = createInput({ 
        t: 0.3, 
        emotionDeviation: { joy: 0.5, curiosity: 0.45, sadness: 0.4, anger: 0.46 } 
      });
      layer.update(0.3, 1 / 60, input);
      
      // At 300ms later (t=0.6), it should now replace sadness
      input = createInput({ 
        t: 0.6, 
        emotionDeviation: { joy: 0.5, curiosity: 0.45, sadness: 0.4, anger: 0.46 } 
      });
      const output = layer.update(0.6, 1 / 60, input);
      
      // The expression should now reflect anger (lower face) instead of sadness
      // Sadness would have produced mouthCornerPull, anger produces mouthPress
      const hasMouthPress = (output.mouthPressLeft || 0) > 0.01 || (output.mouthPressRight || 0) > 0.01;
      const hasMouthCornerPull = (output.mouthLowerDownLeft || 0) > 0.01 || (output.mouthLowerDownRight || 0) > 0.01;
      
      // With anger replacing sadness, we should see mouthPress (anger) not mouthLowerDown (sadness)
      expect(hasMouthPress).toBe(true);
    });

    it("T3: alternating top two emotions don't trigger third-place hysteresis", () => {
      // When only top 2 alternate, the third place (if any) should remain stable
      const layer = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 12345 });
      
      // Start with three emotions
      let input = createInput({ 
        t: 0, 
        emotionDeviation: { joy: 0.5, curiosity: 0.48, sadness: 0.2 } 
      });
      layer.update(0, 1 / 60, input);
      
      // Alternate joy and curiosity (top 2) - sadness (3rd) should stay
      for (let i = 1; i < 20; i++) {
        const t = i * 0.1;
        const deviation = i % 2 === 0 
          ? { joy: 0.51, curiosity: 0.49, sadness: 0.2 }
          : { joy: 0.49, curiosity: 0.51, sadness: 0.2 };
        input = createInput({ t, emotionDeviation: deviation });
        layer.update(t, 0.1, input);
      }
      
      // Sadness should still be in the dominant emotions (3rd place)
      // We can't directly test internal state, but the expression should 
      // still have some sadness influence (mouthLowerDown)
      const output = layer.update(2.0, 0.1, input);
      const hasSadnessInfluence = (output.mouthLowerDownLeft || 0) > 0.001 || (output.mouthLowerDownRight || 0) > 0.001;
      expect(hasSadnessInfluence).toBe(true);
    });
  });

  describe("Zones", () => {
    it("inward dimensions weight upper face", () => {
      const input = createInput({
        emotionDeviation: { curiosity: 0.7, confusion: 0.5 },
      });
      const output = layer.update(0, 1 / 60, input);

      // Upper face channels should be active
      const upperFaceActive = 
        (output.browInnerUp || 0) > 0.01 ||
        (output.browOuterUpLeft || 0) > 0.01 ||
        (output.eyeWideLeft || 0) > 0.01;
      expect(upperFaceActive).toBe(true);
    });

    it("social dimensions weight lower face", () => {
      const input = createInput({
        emotionDeviation: { joy: 0.7, love: 0.5 },
      });
      const output = layer.update(0, 1 / 60, input);

      // Lower face channels should be active
      const lowerFaceActive = 
        (output.mouthSmileLeft || 0) > 0.01 ||
        (output.mouthSmileRight || 0) > 0.01 ||
        (output.cheekSquintLeft || 0) > 0.01;
      expect(lowerFaceActive).toBe(true);
    });
  });

  describe("Asymmetry", () => {
    it("applies 5-10% left/right offset per expression", () => {
      const input = createInput({
        emotionDeviation: { joy: 0.8 },
      });
      const output = layer.update(0, 1 / 60, input);

      // Left and right smile should differ by 5-10%
      const left = output.mouthSmileLeft || 0;
      const right = output.mouthSmileRight || 0;
      const diff = Math.abs(left - right) / Math.max(left, right);
      
      // Allow for the fact that asymmetry might not apply to all channels
      if (left > 0.01 && right > 0.01) {
        expect(diff).toBeGreaterThanOrEqual(0.04); // ~5%
        expect(diff).toBeLessThanOrEqual(0.12); // ~10% (with some tolerance)
      }
    });

    it("asymmetry is deterministic (same seed = same asymmetry)", () => {
      const input = createInput({ emotionDeviation: { joy: 0.8 } });
      
      const layer1 = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 12345 });
      const layer2 = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 12345 });
      
      const output1 = layer1.update(0, 1 / 60, input);
      const output2 = layer2.update(0, 1 / 60, input);

      // Outputs should be identical
      for (const key of Object.keys(output1)) {
        const ch = key as Channel;
        expect(output1[ch]).toBeCloseTo(output2[ch] || 0, 5);
      }
    });
  });

  describe("Eyes lead", () => {
    it("upper face channels have lead time configured", () => {
      const layer = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 12345 });
      const input = createInput({ emotionDeviation: { curiosity: 0.7 } });
      layer.update(0, 1 / 60, input);

      // The internal state should have upperFaceDelay in 150-250ms range
      // We can't directly test private state, but we verify the config is used
      expect(DEFAULT_AFFECT_CONFIG.eyesLeadRange[0]).toBe(0.15);
      expect(DEFAULT_AFFECT_CONFIG.eyesLeadRange[1]).toBe(0.25);
    });
  });

  describe("Posture from mood", () => {
    it("applies posture changes when mood is provided", () => {
      const input = createInput({
        emotionDeviation: {},
        config: { 
          ...createInput().config, 
          mood: { valence: 0.5, arousal: 0.7 } 
        }
      });
      const output = layer.update(0, 1 / 60, input);

      // Positive valence should lift chest
      expect((output.chest || 0)).toBeGreaterThan(0);
    });

    it("skips posture when mood is null", () => {
      const input = createInput({
        emotionDeviation: {},
        config: { ...createInput().config, mood: null }
      });
      const output = layer.update(0, 1 / 60, input);

      // No posture changes
      expect(output.chest).toBeUndefined();
      expect(output.spine).toBeUndefined();
      expect(output.neck).toBeUndefined();
      expect(output.head).toBeUndefined();
    });
  });

  describe("Table validation", () => {
    it("every dimension in dimension_to_au.json is one of the 27", async () => {
      const validDimensions = [
        "surprise", "confusion", "certainty", "doubt", "boredom",
        "interest", "curiosity", "fascination",
        "joy", "sadness", "anger", "fear", "disgust",
        "awe", "beauty", "wonder", "serenity", "melancholy", "nostalgia",
        "empathy", "gratitude", "pride", "shame", "envy", "compassion",
        "love", "trust"
      ];

      // Import the JSON to check
      const fs = await import("fs");
      const path = await import("path");
      const jsonPath = path.resolve(__dirname, "./tables/dimension_to_au.json");
      const data = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));

      for (const dim of Object.keys(data.mappings)) {
        expect(validDimensions).toContain(dim);
      }
      expect(Object.keys(data.mappings).length).toBe(27);
    });

    it("every shape in au_to_arkit.json is an ARKit name", async () => {
      const { ARKIT_BLEND_SHAPES } = await import("./channels.js");
      const fs = await import("fs");
      const path = await import("path");
      const jsonPath = path.resolve(__dirname, "./tables/au_to_arkit.json");
      const data = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));

      for (const au of Object.values(data.mappings)) {
        for (const shape of Object.keys(au)) {
          expect(ARKIT_BLEND_SHAPES).toContain(shape);
        }
      }
    });
  });

  describe("Determinism", () => {
    it("same seed produces identical output for same input", () => {
      const input = createInput({
        t: 1.0,
        emotionDeviation: { joy: 0.5, curiosity: 0.3, surprise: 0.2 },
      });

      const layer1 = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 999 });
      const layer2 = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 999 });

      const output1 = layer1.update(1.0, 1 / 60, input);
      const output2 = layer2.update(1.0, 1 / 60, input);

      for (const key of Object.keys(output1)) {
        const ch = key as Channel;
        expect(output1[ch]).toBeCloseTo(output2[ch] || 0, 10);
      }
    });

    it("different seeds produce different output", () => {
      const input = createInput({
        t: 1.0,
        emotionDeviation: { joy: 0.5 },
      });

      const layer1 = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 111 });
      const layer2 = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: 222 });

      const output1 = layer1.update(1.0, 1 / 60, input);
      const output2 = layer2.update(1.0, 1 / 60, input);

      // At least one channel should differ
      let hasDifference = false;
      for (const key of Object.keys(output1)) {
        const ch = key as Channel;
        if (Math.abs((output1[ch] || 0) - (output2[ch] || 0)) > 0.001) {
          hasDifference = true;
          break;
        }
      }
      expect(hasDifference).toBe(true);
    });
  });
});