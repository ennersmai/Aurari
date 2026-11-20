/**
 * Avatar Controller - Main entry point.
 * Combines six layers with ownership-based mixing.
 */

export * from "./channels.js";
import ownershipData from "./ownership.json" with { type: "json" };
export { ownershipData };
export * from "./layers.js";
export * from "./mixer.js";
export * from "./idle.js";
export { SeededRandom } from "./idle.js";
export * from "./blink.js";
export * from "./lookat.js";
export * from "./events.js";
export * from "./affect.js";

import type { Layer, LayerName, ControllerInput, ControllerConfig } from "./layers.js";
import type { MixResult } from "./mixer.js";
import { CHANNEL_GROUPS, ALL_CHANNELS, Channel } from "./channels.js";
import { Mixer } from "./mixer.js";
import { IdleLayer } from "./idle.js";
import { EventsLayer } from "./events.js";
import { AffectLayer, AffectConfig, DEFAULT_AFFECT_CONFIG } from "./affect.js";
import { LookAtSystem, LookAtConfig, DEFAULT_LOOKAT_CONFIG } from "./lookat.js";
import { DEFAULT_CONFIG } from "./layers.js";
import { DEFAULT_EVENTS_CONFIG } from "./events.js";

/** Main controller that orchestrates all layers. */
export class AvatarController {
  private mixer: Mixer;
  private idleLayer: IdleLayer;
  private eventsLayer: EventsLayer;
  private affectLayer: AffectLayer;
  private lookAtSystem: LookAtSystem;
  private config: ControllerConfig;
  private lookAtConfig: LookAtConfig;
  private layers: Map<LayerName, Layer> = new Map();
  private currentTime = 0;

  constructor(config: Partial<ControllerConfig> = {}, lookAtConfig: Partial<LookAtConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.lookAtConfig = { ...DEFAULT_LOOKAT_CONFIG, ...lookAtConfig };

    this.mixer = new Mixer(this.config);
    this.idleLayer = new IdleLayer(this.config);
    this.eventsLayer = new EventsLayer({ ...DEFAULT_EVENTS_CONFIG, seed: this.config.noiseSeed + 2000 });
    this.affectLayer = new AffectLayer({ ...DEFAULT_AFFECT_CONFIG, seed: this.config.noiseSeed + 3000 });
    this.lookAtSystem = new LookAtSystem(this.lookAtConfig);

    // Register core layers (cognitive, speech, gesture are added later)
    this.mixer.registerLayer(this.idleLayer);
    this.mixer.registerLayer(this.eventsLayer);
    this.mixer.registerLayer(this.affectLayer);
    this.layers.set("idle", this.idleLayer);
    this.layers.set("events", this.eventsLayer);
    this.layers.set("affect", this.affectLayer);
  }

  /** Register additional layers (affect, cognitive, speech, gesture). */
  registerLayer(layer: Layer): void {
    this.mixer.registerLayer(layer);
    this.layers.set(layer.name, layer);
  }

  /** Get a registered layer by name. */
  getLayer(name: LayerName): Layer | undefined {
    return this.layers.get(name);
  }

  /** Update the controller for one frame. */
  update(dt: number, input: Partial<ControllerInput> = {}): MixResult {
    this.currentTime += dt;

    // Build full input with defaults
    const fullInput: ControllerInput = {
      t: this.currentTime,
      dt,
      emotionDeviation: {},
      cognitiveState: "attending",
      isSpeaking: false,
      visemes: {},
      gazeTarget: null,
      eventPulses: [],
      gestureClip: null,
      config: this.config,
      ...input,
    };

    // Update look-at if gaze target provided
    if (fullInput.gazeTarget) {
      const lookAtResult = this.lookAtSystem.update(this.currentTime, dt, fullInput);
      // Look-at result goes to cognitive layer (not implemented yet)
      // For now, we'll add it to the input for layers that need it
    }

    return this.mixer.mix(fullInput);
  }

  /** Trigger an event pulse (surprise, amusement, nod). */
  triggerEvent(type: "surprise" | "amusement" | "nod", strength: number): void {
    switch (type) {
      case "surprise":
        this.eventsLayer.triggerSurprise(strength, this.currentTime);
        break;
      case "amusement":
        this.eventsLayer.triggerAmusement(strength, this.currentTime);
        break;
      case "nod":
        this.eventsLayer.triggerNod(strength, this.currentTime);
        break;
    }
  }

  /** Trigger a custom event pulse. */
  triggerCustomEvent(channels: Partial<Record<Channel, number>>, duration: number): void {
    this.eventsLayer.triggerCustom(channels, duration, this.currentTime);
  }

  /** Force a blink. */
  forceBlink(): void {
    this.eventsLayer.getBlinkGenerator().forceBlink(this.currentTime);
  }

  /** Set gaze target for look-at. */
  setGazeTarget(target: { x: number; y: number; z: number } | null): void {
    // The target is passed through input to update()
  }

  /** Get the mixer (for inspection/testing). */
  getMixer(): Mixer {
    return this.mixer;
  }

  /** Get the events layer. */
  getEventsLayer(): EventsLayer {
    return this.eventsLayer;
  }

  /** Get the affect layer. */
  getAffectLayer(): AffectLayer {
    return this.affectLayer;
  }

  /** Get the look-at system. */
  getLookAtSystem(): LookAtSystem {
    return this.lookAtSystem;
  }

  /** Reset all layers. */
  reset(): void {
    this.currentTime = 0;
    for (const layer of this.layers.values()) {
      layer.reset?.();
    }
    this.lookAtSystem.reset();
  }

  /** Enable/disable a layer. */
  setLayerEnabled(name: LayerName, enabled: boolean): void {
    this.mixer.setLayerEnabled(name, enabled);
  }

  /** Get current time. */
  getTime(): number {
    return this.currentTime;
  }

  /** Set current time (for testing). */
  setTime(t: number): void {
    this.currentTime = t;
  }
}

// Re-export default configs
export { DEFAULT_CONFIG } from "./layers.js";
export { DEFAULT_LOOKAT_CONFIG } from "./lookat.js";
export { DEFAULT_EVENTS_CONFIG } from "./events.js";
export { DEFAULT_BLINK_CONFIG } from "./blink.js";
export { DEFAULT_AFFECT_CONFIG } from "./affect.js";
export type { AffectConfig } from "./affect.js";