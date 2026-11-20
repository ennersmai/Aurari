/**
 * Tests for the Events Layer (deterministic pulse durations).
 */

import { describe, it, expect, beforeEach } from "vitest";
import { EventsLayer, DEFAULT_EVENTS_CONFIG } from "./events.js";
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

describe("EventsLayer", () => {
  let layer: EventsLayer;

  beforeEach(() => {
    layer = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 12345 });
  });

  describe("Deterministic pulse durations", () => {
    it("two controllers with same seed produce identical event pulses", () => {
      const layer1 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 555 });
      const layer2 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 555 });

      const input = createInput({ t: 0 });

      // Trigger surprise on both
      layer1.triggerSurprise(0.8, 0);
      layer2.triggerSurprise(0.8, 0);

      // Update both for several frames
      for (let i = 0; i < 60; i++) {
        const t = i / 60;
        const out1 = layer1.update(t, 1 / 60, input);
        const out2 = layer2.update(t, 1 / 60, input);

        // All channels should match exactly
        const allChannels = new Set([...Object.keys(out1), ...Object.keys(out2)]);
        for (const ch of allChannels) {
          expect(out1[ch as Channel]).toBeCloseTo(out2[ch as Channel] || 0, 10);
        }
      }
    });

    it("surprise pulse duration is deterministic", () => {
      const layer1 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 777 });
      const layer2 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 777 });

      layer1.triggerSurprise(1.0, 0);
      layer2.triggerSurprise(1.0, 0);

      const input = createInput({ t: 0 });
      const out1 = layer1.update(0, 1 / 60, input);
      const out2 = layer2.update(0, 1 / 60, input);

      // First frame should have identical values
      for (const ch of Object.keys(out1)) {
        expect(out1[ch as Channel]).toBeCloseTo(out2[ch as Channel] || 0, 10);
      }
    });

    it("amusement pulse duration is deterministic", () => {
      const layer1 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 888 });
      const layer2 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 888 });

      layer1.triggerAmusement(0.7, 0);
      layer2.triggerAmusement(0.7, 0);

      const input = createInput({ t: 0 });
      const out1 = layer1.update(0, 1 / 60, input);
      const out2 = layer2.update(0, 1 / 60, input);

      for (const ch of Object.keys(out1)) {
        expect(out1[ch as Channel]).toBeCloseTo(out2[ch as Channel] || 0, 10);
      }
    });

    it("nod pulse duration is deterministic", () => {
      const layer1 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 999 });
      const layer2 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 999 });

      layer1.triggerNod(0.5, 0);
      layer2.triggerNod(0.5, 0);

      const input = createInput({ t: 0 });
      const out1 = layer1.update(0, 1 / 60, input);
      const out2 = layer2.update(0, 1 / 60, input);

      for (const ch of Object.keys(out1)) {
        expect(out1[ch as Channel]).toBeCloseTo(out2[ch as Channel] || 0, 10);
      }
    });

    it("different seeds produce different pulse durations", () => {
      const layer1 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 111 });
      const layer2 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 222 });

      layer1.triggerSurprise(1.0, 0);
      layer2.triggerSurprise(1.0, 0);

      const input = createInput({ t: 0 });
      // Run a few frames to get past the initial zero progress
      for (let i = 0; i < 5; i++) {
        layer1.update(i / 60, 1 / 60, input);
        layer2.update(i / 60, 1 / 60, input);
      }
      const out1 = layer1.update(5 / 60, 1 / 60, input);
      const out2 = layer2.update(5 / 60, 1 / 60, input);

      // At least one channel should differ
      let hasDifference = false;
      for (const ch of Object.keys(out1)) {
        if (Math.abs((out1[ch as Channel] || 0) - (out2[ch as Channel] || 0)) > 0.001) {
          hasDifference = true;
          break;
        }
      }
      expect(hasDifference).toBe(true);
    });
  });

  describe("Pulse decay", () => {
    it("pulse returns to zero within duration", () => {
      layer.triggerSurprise(1.0, 0);
      const input = createInput({ t: 0 });

      // Update for 600ms (max pulse duration)
      let lastOutput: Record<string, number> = {};
      for (let i = 0; i <= 36; i++) { // 36 frames at 60fps = 600ms
        const t = i / 60;
        lastOutput = layer.update(t, 1 / 60, input);
      }

      // After 600ms, pulse should be finished (all channels zero)
      for (const value of Object.values(lastOutput)) {
        expect(Math.abs(value)).toBeLessThan(0.001);
      }
    });

    it("pulse curve is smooth (attack then decay)", () => {
      layer.triggerSurprise(1.0, 0);
      const input = createInput({ t: 0 });

      const values: number[] = [];
      for (let i = 0; i < 30; i++) {
        const t = i / 60;
        const output = layer.update(t, 1 / 60, input);
        // Track browInnerUp as representative
        values.push(output.browInnerUp || 0);
      }

      // Should rise then fall
      const maxIdx = values.indexOf(Math.max(...values));
      expect(maxIdx).toBeGreaterThan(0);
      expect(maxIdx).toBeLessThan(values.length - 1);
    });
  });

  describe("Blink integration", () => {
    it("blink generator produces deterministic blinks", () => {
      const layer1 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 333 });
      const layer2 = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: 333 });

      const input = createInput({ t: 0, gazeTarget: { x: 0, y: 0, z: -1 } });

      for (let i = 0; i < 600; i++) { // 10 seconds
        const t = i / 60;
        const out1 = layer1.update(t, 1 / 60, input);
        const out2 = layer2.update(t, 1 / 60, input);

        for (const ch of Object.keys(out1)) {
          expect(out1[ch as Channel]).toBeCloseTo(out2[ch as Channel] || 0, 10);
        }
      }
    });
  });

  describe("Reset", () => {
    it("reset clears all pulses and resets random generator", () => {
      layer.triggerSurprise(1.0, 0);
      layer.triggerAmusement(0.5, 1.0);
      
      const input = createInput({ t: 2.0 });
      layer.update(2.0, 1 / 60, input);
      
      layer.reset();
      
      // After reset, no pulses should be active
      const output = layer.update(2.5, 1 / 60, input);
      for (const value of Object.values(output)) {
        expect(Math.abs(value)).toBeLessThan(0.001);
      }
    });
  });
});