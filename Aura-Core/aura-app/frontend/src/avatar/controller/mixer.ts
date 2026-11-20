/**
 * Mixer: combines the six layers' outputs per frame under the ownership table.
 * Determines the winning layer per channel; event pulses add; speech scales lower-face affect to 30% while speaking.
 * Records which layer wrote each channel (for test T2).
 */

import type {
  Layer,
  LayerName,
  LayerOutput,
  ControllerInput,
  ControllerConfig,
} from "./layers";
import type { Channel, ChannelGroup } from "./channels";
import { CHANNEL_GROUPS, CHANNELS_BY_GROUP, ALL_CHANNELS } from "./channels";
import ownershipData from "./ownership.json" with { type: "json" };

/** Ownership entry from JSON. */
interface OwnershipEntry {
  layer: LayerName;
  priority: number;
}

/** Parsed ownership table: group -> layers with priority (highest wins). */
type OwnershipTable = Record<ChannelGroup, OwnershipEntry[]>;

/** Result of mixing: final channel values and which layer wrote each. */
export interface MixResult {
  /** Final channel values for this frame. */
  channels: Record<Channel, number>;
  /** Which layer wrote each channel (for debugging/tests). */
  writer: Record<Channel, LayerName | null>;
}

/** Internal layer state for the mixer. */
interface LayerState {
  layer: Layer;
  enabled: boolean;
}

/**
 * Mixer class that combines layer outputs according to ownership rules.
 */
export class Mixer {
  private layers: Map<LayerName, LayerState> = new Map();
  private ownership: OwnershipTable;
  private config: ControllerConfig;
  private lastWriter: Record<Channel, LayerName | null>;

  constructor(config: ControllerConfig = DEFAULT_CONFIG) {
    this.config = config;
    this.ownership = this.parseOwnership(ownershipData);
    this.lastWriter = Object.fromEntries(ALL_CHANNELS.map((c) => [c, null])) as Record<Channel, LayerName | null>;
  }

  /** Register a layer with the mixer. */
  registerLayer(layer: Layer): void {
    this.layers.set(layer.name, { layer, enabled: true });
  }

  /** Enable or disable a layer by name. */
  setLayerEnabled(name: LayerName, enabled: boolean): void {
    const state = this.layers.get(name);
    if (state) state.enabled = enabled;
  }

  /** Update all layers and mix their outputs for one frame. */
  mix(input: ControllerInput): MixResult {
    // Collect outputs from all enabled layers
    const layerOutputs: Map<LayerName, LayerOutput> = new Map();
    for (const [name, state] of this.layers) {
      if (state.enabled) {
        layerOutputs.set(name, state.layer.update(input.t, input.dt, input));
      }
    }

    // Determine writer and final value for each channel
    const channels: Record<Channel, number> = {} as Record<Channel, number>;
    const writer: Record<Channel, LayerName | null> = {} as Record<Channel, LayerName | null>;

    for (const channel of ALL_CHANNELS) {
      const group = CHANNEL_GROUPS[channel];
      const allowedLayers = this.ownership[group];
      let winningLayer: LayerName | null = null;
      let winningValue = 0;
      let winningPriority = -1;

      // Find the highest-priority layer that wrote this channel
      for (const entry of allowedLayers) {
        const output = layerOutputs.get(entry.layer);
        if (output && channel in output) {
          if (entry.priority > winningPriority) {
            winningPriority = entry.priority;
            winningLayer = entry.layer;
            winningValue = output[channel]!;
          }
        }
      }

      // Special rule: speech scales lower-face affect to 30% while speaking
      if (winningLayer === "speech" && group === "lowerFace" && input.isSpeaking) {
        // Find affect's value for this channel and scale it
        const affectOutput = layerOutputs.get("affect");
        if (affectOutput && channel in affectOutput) {
          // Speech wins, but we blend: speech value + 30% of affect value
          const affectValue = affectOutput[channel]!;
          winningValue = winningValue + affectValue * 0.3;
        }
      }

      // Event pulses are additive: they add to the winning value
      // (Events layer already outputs additive pulses, but we ensure they add)
      const eventsOutput = layerOutputs.get("events");
      if (eventsOutput && channel in eventsOutput) {
        // Only add if events layer didn't already win (i.e., not the highest priority)
        if (winningLayer !== "events") {
          winningValue += eventsOutput[channel]!;
        }
      }

      channels[channel] = winningValue;
      writer[channel] = winningLayer;
    }

    this.lastWriter = writer;
    return { channels, writer };
  }

  /** Get the writer map from the last mix (for tests). */
  getLastWriter(): Record<Channel, LayerName | null> {
    return { ...this.lastWriter };
  }

  /** Parse ownership JSON into a typed table. */
  private parseOwnership(data: typeof ownershipData): OwnershipTable {
    const table: Partial<OwnershipTable> = {};
    for (const [group, entry] of Object.entries(data)) {
      table[group as ChannelGroup] = entry.layers.map((l) => ({
        layer: l.layer as LayerName,
        priority: l.priority,
      }));
    }
    return table as OwnershipTable;
  }
}

/** Default config for the mixer. */
export const DEFAULT_CONFIG: ControllerConfig = {
  noiseSeed: 42,
  breathingRate: 0.25,
  weightShiftRate: 0.1,
  blinkInterval: [2, 6],
  lookAtSmoothing: {
    eyes: 0.15,
    head: 0.3,
    chest: 0.5,
  },
};