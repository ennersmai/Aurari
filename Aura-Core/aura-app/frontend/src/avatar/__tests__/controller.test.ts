/**
 * Tests for the Avatar Controller (W3-35).
 * T2: Channel ownership - no channel written by unauthorized layer.
 * T6: Event pulse decay, blink timing, idle determinism.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  AvatarController,
  Mixer,
  IdleLayer,
  EventsLayer,
  LookAtSystem,
  BlinkGenerator,
  DEFAULT_CONFIG,
  DEFAULT_EVENTS_CONFIG,
  DEFAULT_BLINK_CONFIG,
  DEFAULT_LOOKAT_CONFIG,
} from "../controller/index.js";
import { CHANNEL_GROUPS, ALL_CHANNELS, CHANNELS_BY_GROUP, isFaceShape } from "../controller/channels.js";
import ownershipData from "../controller/ownership.json" with { type: "json" };
import type { ControllerInput, EventPulse, LayerName } from "../controller/layers.js";

// Helper to create a minimal controller input
function createInput(overrides: Partial<ControllerInput> = {}): ControllerInput {
  return {
    t: 0,
    dt: 1/60,
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

describe("W3-35 Controller Skeleton", () => {
  describe("T2: Channel Ownership", () => {
    let controller: AvatarController;
    let mixer: Mixer;

    beforeEach(() => {
      controller = new AvatarController();
      mixer = controller.getMixer();
    });

    it("should only allow authorized layers to write each channel group", () => {
      // Simulate 600 frames with all layers active
      const frames = 600;
      const unauthorizedWrites: Array<{ channel: string; layer: string; group: string }> = [];

      // Register mock layers for all six layers
      const mockLayers: Record<LayerName, { update: (t: number, dt: number, input: ControllerInput) => Record<string, number> }> = {
        idle: { update: () => ({ spine: 0.1, chest: 0.1, neck: 0.1, head: 0.05, eyeL: 0.01, eyeR: 0.01, shoulderL: 0.01, shoulderR: 0.01 }) },
        affect: { update: () => ({ browInnerUp: 0.5, eyeBlinkLeft: 0.3, mouthSmileLeft: 0.4, mouthSmileRight: 0.4, jawOpen: 0.2 }) },
        cognitive: { update: () => ({ eyeL: 0.3, eyeR: 0.3, head: 0.2, browInnerUp: 0.1 }) },
        events: { update: () => ({ browInnerUp: 0.8, eyeWideLeft: 0.6, eyeWideRight: 0.6, head: 0.1 }) },
        speech: { update: () => ({ jawOpen: 0.8, mouthOpen: 0.7, mouthPucker: 0.3 }) },
        gesture: { update: () => ({ shoulderL: 0.5, shoulderR: 0.5, upperArmL: 0.4, upperArmR: 0.4, head: 0.3, spine: 0.2 }) },
      };

      // Register all mock layers with the mixer
      for (const [name, layer] of Object.entries(mockLayers)) {
        mixer.registerLayer({
          name: name as LayerName,
          groups: ownershipData[Object.keys(CHANNELS_BY_GROUP).find(g => 
            ownershipData[g].layers.some(l => l.layer === name)
          ) || "body"].layers.map(l => l.layer),
          update: (t, dt, input) => layer.update(t, dt, input),
        });
      }

      for (let frame = 0; frame < frames; frame++) {
        const t = frame / 60;
        const dt = 1/60;
        const input = createInput({ t, dt });

        const result = mixer.mix(input);

        // Check each channel's writer against ownership table
        for (const [channel, writer] of Object.entries(result.writer)) {
          if (writer !== null) {
            const group = CHANNEL_GROUPS[channel as keyof typeof CHANNEL_GROUPS];
            const allowedLayers = ownershipData[group].layers.map(l => l.layer);
            
            if (!allowedLayers.includes(writer)) {
              unauthorizedWrites.push({ channel, layer: writer, group });
            }
          }
        }
      }

      expect(unauthorizedWrites).toHaveLength(0);
    });

    it("gesture layer should never write face shapes", () => {
      const frames = 600;
      const faceShapeWrites: string[] = [];

      // Register gesture layer that tries to write face shapes
      mixer.registerLayer({
        name: "gesture",
        groups: ["arms", "body", "head"],
        update: () => ({
          shoulderL: 0.5,
          shoulderR: 0.5,
          upperArmL: 0.4,
          // These are face shapes - gesture should NOT write them
          browInnerUp: 0.3,
          mouthSmileLeft: 0.4,
          eyeBlinkLeft: 0.2,
        }),
      });

      for (let frame = 0; frame < frames; frame++) {
        const t = frame / 60;
        const dt = 1/60;
        const input = createInput({ t, dt });

        const result = mixer.mix(input);

        // Check if gesture wrote any face shape
        for (const [channel, writer] of Object.entries(result.writer)) {
          if (writer === "gesture" && isFaceShape(channel as any)) {
            faceShapeWrites.push(channel);
          }
        }
      }

      expect(faceShapeWrites).toHaveLength(0);
    });
  });

  describe("T6: Event Pulse Decay, Blink Timing, Idle Determinism", () => {
    describe("Event Pulse Decay", () => {
      it("every event pulse should return to exactly zero within 600ms", () => {
        const eventsLayer = new EventsLayer(DEFAULT_EVENTS_CONFIG);
        const pulseDuration = 0.5; // 500ms
        const startTime = 0;

        // Trigger a custom pulse
        eventsLayer.triggerCustom(
          { browInnerUp: 1.0, eyeWideLeft: 1.0, eyeWideRight: 1.0 },
          pulseDuration,
          startTime
        );

        // Simulate frames up to 600ms
        const frames = Math.ceil(0.6 / (1/60)) + 10; // 600ms + buffer
        let pulseActive = true;
        let returnedToZero = false;

        for (let frame = 0; frame < frames; frame++) {
          const t = frame / 60;
          const dt = 1/60;
          const input = createInput({ t, dt });

          const output = eventsLayer.update(t, dt, input);

          // Check if pulse channels are active
          const hasActivePulse = (output.browInnerUp ?? 0) > 0 || 
                                 (output.eyeWideLeft ?? 0) > 0 || 
                                 (output.eyeWideRight ?? 0) > 0;

          if (pulseActive && !hasActivePulse) {
            returnedToZero = true;
            const elapsed = t - startTime;
            expect(elapsed).toBeLessThanOrEqual(0.6); // Within 600ms
            pulseActive = false;
          }
        }

        expect(returnedToZero).toBe(true);
      });

      it("surprise pulse should decay to zero within 600ms", () => {
        const eventsLayer = new EventsLayer(DEFAULT_EVENTS_CONFIG);
        const startTime = 0;

        eventsLayer.triggerSurprise(1.0, startTime);

        const frames = Math.ceil(0.6 / (1/60)) + 10;
        let returnedToZero = false;

        for (let frame = 0; frame < frames; frame++) {
          const t = frame / 60;
          const dt = 1/60;
          const input = createInput({ t, dt });

          const output = eventsLayer.update(t, dt, input);

          const hasActivePulse = (output.browInnerUp ?? 0) > 0 || 
                                 (output.eyeWideLeft ?? 0) > 0 || 
                                 (output.eyeWideRight ?? 0) > 0 ||
                                 (output.jawOpen ?? 0) > 0;

          if (!hasActivePulse && t > startTime + 0.1) { // After pulse should have started
            returnedToZero = true;
            expect(t - startTime).toBeLessThanOrEqual(0.6);
            break;
          }
        }

        expect(returnedToZero).toBe(true);
      });

      it("amusement pulse should decay to zero within 600ms", () => {
        const eventsLayer = new EventsLayer(DEFAULT_EVENTS_CONFIG);
        const startTime = 0;

        eventsLayer.triggerAmusement(1.0, startTime);

        const frames = Math.ceil(0.6 / (1/60)) + 10;
        let returnedToZero = false;

        for (let frame = 0; frame < frames; frame++) {
          const t = frame / 60;
          const dt = 1/60;
          const input = createInput({ t, dt });

          const output = eventsLayer.update(t, dt, input);

          const hasActivePulse = (output.mouthSmileLeft ?? 0) > 0 || 
                                 (output.mouthSmileRight ?? 0) > 0 ||
                                 (output.cheekSquintLeft ?? 0) > 0 ||
                                 (output.eyeSquintLeft ?? 0) > 0;

          if (!hasActivePulse && t > startTime + 0.1) {
            returnedToZero = true;
            expect(t - startTime).toBeLessThanOrEqual(0.6);
            break;
          }
        }

        expect(returnedToZero).toBe(true);
      });
    });

    describe("Blink Timing", () => {
      it("blink should happen within 6 seconds", () => {
        const blinkGenerator = new BlinkGenerator({ ...DEFAULT_BLINK_CONFIG, minInterval: 2, maxInterval: 6 });
        blinkGenerator.reset(0);

        let blinkOccurred = false;
        let blinkTime = 0;

        // Simulate for 7 seconds
        for (let frame = 0; frame < 7 * 60; frame++) {
          const t = frame / 60;
          const dt = 1/60;
          const input = createInput({ t, dt });

          const result = blinkGenerator.update(t, dt, input);

          if (result.isBlinking && !blinkOccurred) {
            blinkOccurred = true;
            blinkTime = t;
          }

          if (blinkOccurred && !result.isBlinking) {
            // Blink completed
            break;
          }
        }

        expect(blinkOccurred).toBe(true);
        expect(blinkTime).toBeLessThanOrEqual(6); // Within 6 seconds
      });

      it("blink should trigger on large gaze shift", () => {
        const blinkGenerator = new BlinkGenerator(DEFAULT_BLINK_CONFIG);
        blinkGenerator.reset(0);

        // Advance to just before a scheduled blink
        let result = blinkGenerator.update(0.1, 1/60, createInput({ t: 0.1, dt: 1/60 }));
        expect(result.isBlinking).toBe(false);

        // Large gaze shift (more than threshold ~0.5 rad = ~28 degrees)
        const largeGazeTarget = { x: 1, y: 0, z: -1 }; // ~45 degrees
        result = blinkGenerator.update(0.2, 1/60, createInput({ 
          t: 0.2, 
          dt: 1/60, 
          gazeTarget: largeGazeTarget 
        }));

        expect(result.isBlinking).toBe(true);
      });
    });

    describe("Idle Determinism", () => {
      it("idle output should be deterministic for the same seed", () => {
        const config1 = { ...DEFAULT_CONFIG, noiseSeed: 42 };
        const config2 = { ...DEFAULT_CONFIG, noiseSeed: 42 };

        const idle1 = new IdleLayer(config1);
        const idle2 = new IdleLayer(config2);

        // Run for 100 frames
        const frames = 100;
        const outputs1: Array<Record<string, number>> = [];
        const outputs2: Array<Record<string, number>> = [];

        for (let frame = 0; frame < frames; frame++) {
          const t = frame / 60;
          const dt = 1/60;
          const input = createInput({ t, dt, config: config1 });

          outputs1.push(idle1.update(t, dt, input));
          outputs2.push(idle2.update(t, dt, input));
        }

        // Compare outputs - should be identical
        for (let i = 0; i < frames; i++) {
          const out1 = outputs1[i];
          const out2 = outputs2[i];
          
          for (const key of Object.keys(out1)) {
            expect(out1[key]).toBeCloseTo(out2[key], 10);
          }
          for (const key of Object.keys(out2)) {
            expect(out2[key]).toBeCloseTo(out1[key], 10);
          }
        }
      });

      it("idle output should differ with different seeds", () => {
        const config1 = { ...DEFAULT_CONFIG, noiseSeed: 42 };
        const config2 = { ...DEFAULT_CONFIG, noiseSeed: 123 };

        const idle1 = new IdleLayer(config1);
        const idle2 = new IdleLayer(config2);

        const input = createInput({ t: 1, dt: 1/60, config: config1 });
        const out1 = idle1.update(1, 1/60, input);
        const out2 = idle2.update(1, 1/60, { ...input, config: config2 });

        // At least one channel should differ
        let hasDifference = false;
        for (const key of Object.keys(out1)) {
          if (Math.abs((out1[key] ?? 0) - (out2[key] ?? 0)) > 0.001) {
            hasDifference = true;
            break;
          }
        }
        expect(hasDifference).toBe(true);
      });
    });
  });

  describe("LookAt System", () => {
    it("should smoothly track a target with eyes, head, and chest", () => {
      const lookAt = new LookAtSystem(DEFAULT_LOOKAT_CONFIG);
      const target = { x: 1, y: 0.5, z: -2 };

      // Simulate tracking for 1 second
      for (let frame = 0; frame < 60; frame++) {
        const t = frame / 60;
        const dt = 1/60;
        const input = createInput({ t, dt, gazeTarget: target });

        const result = lookAt.update(t, dt, input);

        // Should move toward target
        if (frame === 59) {
          expect(Math.abs(result.eyeRotation.yaw)).toBeGreaterThan(0);
          expect(Math.abs(result.headRotation.yaw)).toBeGreaterThan(0);
          expect(Math.abs(result.chestRotation.yaw)).toBeGreaterThan(0);
        }
      }
    });

    it("should return to neutral when target is removed", () => {
      const lookAt = new LookAtSystem(DEFAULT_LOOKAT_CONFIG);
      const target = { x: 1, y: 0, z: -1 };

      // Track target for a bit
      for (let frame = 0; frame < 30; frame++) {
        const t = frame / 60;
        const dt = 1/60;
        lookAt.update(t, dt, createInput({ t, dt, gazeTarget: target }));
      }

      // Remove target - run for 2 seconds (120 frames) to allow settling
      for (let frame = 30; frame < 150; frame++) {
        const t = frame / 60;
        const dt = 1/60;
        const result = lookAt.update(t, dt, createInput({ t, dt, gazeTarget: null }));

        if (frame === 149) {
          // Should be close to neutral after 2 seconds
          expect(Math.abs(result.eyeRotation.yaw)).toBeLessThan(0.01);
          expect(Math.abs(result.headRotation.yaw)).toBeLessThan(0.01);
          expect(Math.abs(result.chestRotation.yaw)).toBeLessThan(0.01);
        }
      }
    });
  });

  describe("Ownership Table Structure", () => {
    it("should have all 7 channel groups defined", () => {
      const groups = Object.keys(ownershipData);
      expect(groups).toContain("upperFace");
      expect(groups).toContain("lowerFace");
      expect(groups).toContain("eyes");
      expect(groups).toContain("jaw");
      expect(groups).toContain("head");
      expect(groups).toContain("body");
      expect(groups).toContain("arms");
    });

    it("each group should have layers with priorities", () => {
      for (const [group, data] of Object.entries(ownershipData)) {
        expect(data.layers).toBeInstanceOf(Array);
        expect(data.layers.length).toBeGreaterThan(0);
        
        for (const layer of data.layers) {
          expect(layer.layer).toBeDefined();
          expect(typeof layer.priority).toBe("number");
        }
        
        // Priorities should be unique within a group
        const priorities = data.layers.map(l => l.priority);
        const uniquePriorities = new Set(priorities);
        expect(uniquePriorities.size).toBe(priorities.length);
      }
    });

    it("idle layer should have priority 1 in all groups", () => {
      for (const [group, data] of Object.entries(ownershipData)) {
        const idleLayer = data.layers.find(l => l.layer === "idle");
        expect(idleLayer).toBeDefined();
        expect(idleLayer!.priority).toBe(1);
      }
    });

    it("gesture layer should not be in face groups", () => {
      // Gesture should only be in arms, body, head (not upperFace, lowerFace, eyes, jaw)
      const faceGroups = ["upperFace", "lowerFace", "eyes", "jaw"];
      
      for (const group of faceGroups) {
        const gestureLayer = ownershipData[group].layers.find(l => l.layer === "gesture");
        expect(gestureLayer).toBeUndefined();
      }

      // But should be in arms, body, head
      const bodyGroups = ["arms", "body", "head"];
      for (const group of bodyGroups) {
        const gestureLayer = ownershipData[group].layers.find(l => l.layer === "gesture");
        expect(gestureLayer).toBeDefined();
      }
    });
  });
});