/**
 * Inference Cockpit — TypeScript types
 *
 * Mirrors the Pydantic models in inference_config.py.
 * Keep these in sync with any schema changes.
 */

export interface InferenceConfig {
  // Sampling
  temperature: number;
  top_p: number;
  min_p: number;
  frequency_penalty: number;
  presence_penalty: number;
  context_length: number;
  max_tokens: number;
  // Layer toggles
  layer_l1_enabled: boolean;
  layer_l2_enabled: boolean;
  layer_l3_enabled: boolean;
  layer_l4_enabled: boolean;
  layer_l5_enabled: boolean;
  // Routing
  local_mode_enabled: boolean;
  sglang_enabled: boolean;
  model_stack_index: number;
}

export interface ActiveModels {
  l1: string;
  l2: string;
  l3: string;
  l4: string;
  l5: string;
  embeddings: string;
}

export interface InferenceConfigResponse {
  success: boolean;
  config: InferenceConfig;
  active_models: ActiveModels;
}

/** Risk level for VRAM usage on a 3090 24 GB */
export type VRAMRisk = "safe" | "warning" | "danger";

export const DEFAULT_INFERENCE_CONFIG: InferenceConfig = {
  temperature: 0.7,
  top_p: 0.9,
  min_p: 0.05,
  frequency_penalty: 0.0,
  presence_penalty: 0.0,
  context_length: 8192,
  max_tokens: 2048,
  layer_l1_enabled: true,
  layer_l2_enabled: true,
  layer_l3_enabled: true,
  layer_l4_enabled: true,
  layer_l5_enabled: true,
  local_mode_enabled: false,
  sglang_enabled: false,
  model_stack_index: 0,
};

/** Compute 3090 VRAM risk from context length.
 *  Based on 24 GB card with a typical 24B Q4_K_M model (~13 GB weights). */
export function getVRAMRisk(ctx: number): VRAMRisk {
  if (ctx <= 16384) return "safe";
  if (ctx <= 49152) return "warning";
  return "danger";
}

export function formatContextK(tokens: number): string {
  return `${Math.round(tokens / 1024)}k`;
}
