/**
 * Tests for the Cognitive Layer (W3-38).
 * T16: Cognitive layer outputs per state.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { CognitiveLayer } from "./cognitive.js";
import type { ControllerInput } from "./layers.js";
import { DEFAULT_CONFIG } from "./layers.js";

// Helper to create a minimal controller input
function createInput(overrides: Partial<ControllerInput> = {}): ControllerInput {
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
    config: DEFAULT_CONFIG,
    ...overrides,
  };
}

// Run N frames to let smooth transitions converge
function runFrames(layer: CognitiveLayer, input: ControllerInput, frames: number) {
  let output: ReturnType<typeof layer.update>;
  for (let i = 0; i < frames; i++) {
    output = layer.update(i / 60, 1 / 60, input);
  }
  return output;
}

describe("W3-38 Cognitive Layer", () => {
  let layer: CognitiveLayer;

  beforeEach(() => {
    layer = new CognitiveLayer();
  });

  describe("outputs per cognitive state", () => {
    const states = [
      "attending",
      "recalling",
      "thinking",
      "unsure",
      "found_it",
      "surprised",
      "working",
      "curious",
      "resting",
      "idle",
    ];

    it.each(states)("should produce outputs for state %s", (state) => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: state });
      const output = layer.update(0, 1 / 60, input);

      // Should always produce some output
      expect(output).toBeDefined();
      expect(typeof output).toBe("object");
    });

    it("attending: gaze forward, slight brow inner up", () => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "attending" });
      // Run enough frames for smooth transition to converge (~3 seconds at 60fps)
      const output = runFrames(layer, input, 200);

      // Brow inner up should be active (converges to 0.2)
      expect(output.browInnerUp).toBeCloseTo(0.2, 1);
    });

    it("surprised: high brow modifiers", () => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "surprised" });
      const output = runFrames(layer, input, 200);

      // Surprised state has high brow inner up (converges to 0.8)
      expect(output.browInnerUp).toBeGreaterThan(0.5);
      expect(output.browOuterUpLeft).toBeGreaterThan(0.5);
      expect(output.browOuterUpRight).toBeGreaterThan(0.5);
    });

    it("thinking: gaze to the left, head tilted left", () => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "thinking" });
      const output = runFrames(layer, input, 200);

      // Thinking state has gazeTarget x=-0.3 (left), headTilt=-0.15
      expect(output.eyeL).toBeLessThan(0);
      expect(output.eyeR).toBeLessThan(0);
      expect(output.head).toBeCloseTo(-0.15, 1);
    });

    it("curious: gaze to the right, head tilted right", () => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "curious" });
      const output = runFrames(layer, input, 200);

      // Curious state has gazeTarget x=0.3 (right), headTilt=0.15
      expect(output.eyeL).toBeGreaterThan(0);
      expect(output.eyeR).toBeGreaterThan(0);
      expect(output.head).toBeCloseTo(0.15, 1);
    });

    it("resting: no gaze, no head tilt, no brow modifiers", () => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "resting" });
      const output = layer.update(0, 1 / 60, input);

      expect(output.head).toBeCloseTo(0, 1);
      expect(output.browInnerUp).toBeUndefined();
      expect(output.browOuterUpLeft).toBeUndefined();
      expect(output.browOuterUpRight).toBeUndefined();
    });

    it("idle: same as resting", () => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "idle" });
      const output = layer.update(0, 1 / 60, input);

      expect(output.head).toBeCloseTo(0, 1);
      expect(output.browInnerUp).toBeUndefined();
    });

    it("unknown state defaults to attending", () => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "unknown_state" as any });
      const output = runFrames(layer, input, 200);

      // Should default to attending config
      expect(output.browInnerUp).toBeCloseTo(0.2, 1);
    });
  });

  describe("smooth transitions", () => {
    it("should transition head tilt smoothly between states", () => {
      // Start in resting (headTilt=0)
      let input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "resting" });
      let output = layer.update(0, 1 / 60, input);
      expect(output.head).toBeCloseTo(0, 2);

      // Switch to curious (headTilt=0.15)
      input = createInput({ t: 1 / 60, dt: 1 / 60, cognitiveState: "curious" });
      output = layer.update(1 / 60, 1 / 60, input);
      // Should not instantly reach 0.15, but move toward it
      expect(output.head).toBeGreaterThan(0);
      expect(output.head).toBeLessThan(0.15);

      // Continue updating curious state
      for (let i = 2; i < 300; i++) {
        input = createInput({ t: i / 60, dt: 1 / 60, cognitiveState: "curious" });
        output = layer.update(i / 60, 1 / 60, input);
      }
      // Should be close to the target after many frames
      expect(output.head).toBeCloseTo(0.15, 1);
    });

    it("should transition brow modifiers smoothly", () => {
      // Start in attending and converge (browInnerUp=0.2)
      let input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "attending" });
      let output = runFrames(layer, input, 300);
      expect(output.browInnerUp).toBeCloseTo(0.2, 1);

      // Switch to surprised (browInnerUp=0.8)
      input = createInput({ t: 300 / 60, dt: 1 / 60, cognitiveState: "surprised" });
      output = layer.update(300 / 60, 1 / 60, input);
      // Should move toward 0.8 but not instantly reach it
      expect(output.browInnerUp).toBeGreaterThan(0.2);
      expect(output.browInnerUp).toBeLessThan(0.8);

      // Continue updating surprised state
      for (let i = 301; i < 900; i++) {
        input = createInput({ t: i / 60, dt: 1 / 60, cognitiveState: "surprised" });
        output = layer.update(i / 60, 1 / 60, input);
      }
      expect(output.browInnerUp).toBeCloseTo(0.8, 1);
    });
  });

  describe("reset", () => {
    it("should reset internal state", () => {
      // Drive to surprised state
      let input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "surprised" });
      for (let i = 0; i < 100; i++) {
        input = createInput({ t: i / 60, dt: 1 / 60, cognitiveState: "surprised" });
        layer.update(i / 60, 1 / 60, input);
      }
      let output = layer.update(100 / 60, 1 / 60, input);
      expect(output.browInnerUp).toBeCloseTo(0.8, 1);

      // Reset and check
      layer.reset();
      input = createInput({ t: 101 / 60, dt: 1 / 60, cognitiveState: "resting" });
      output = layer.update(101 / 60, 1 / 60, input);
      expect(output.head).toBeCloseTo(0, 1);
    });
  });

  describe("filtering", () => {
    it("should only output channels in its owned groups", () => {
      const input = createInput({ t: 0, dt: 1 / 60, cognitiveState: "surprised" });
      const output = layer.update(0, 1 / 60, input);

      // Cognitive owns upperFace, eyes, head
      // Should NOT write jaw, mouth, body, arms channels
      const forbiddenChannels = ["jawOpen", "mouthSmileLeft", "spine", "chest", "shoulderL"];
      for (const ch of forbiddenChannels) {
        expect(output[ch as any]).toBeUndefined();
      }

      // Should write brow, eye, head channels
      expect(output.browInnerUp).toBeDefined();
      expect(output.eyeL).toBeDefined();
      expect(output.head).toBeDefined();
    });
  });
});
