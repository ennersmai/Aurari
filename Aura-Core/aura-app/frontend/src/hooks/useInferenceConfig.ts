/**
 * useInferenceConfig — Inference Cockpit data hook
 *
 * Fetches the live inference config from the backend and provides
 * a debounced mutation function so slider changes don't flood the API.
 *
 * Usage:
 *   const { config, activeModels, isLoading, updateConfig } = useInferenceConfig();
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE_URL } from "@/config";
import {
  InferenceConfig,
  ActiveModels,
  DEFAULT_INFERENCE_CONFIG,
} from "@/types/inference";

const ENDPOINT = `${API_BASE_URL}/system/inference-config`;
const STACK_ENDPOINT = `${API_BASE_URL}/system/model-stack`;
const DEBOUNCE_MS = 400;

interface UseInferenceConfigReturn {
  config: InferenceConfig;
  activeModels: ActiveModels | null;
  isLoading: boolean;
  isSaving: boolean;
  /** Partially update any fields in the config — debounced POST to backend */
  updateConfig: (patch: Partial<InferenceConfig>) => void;
  /** Force an immediate sync (bypass debounce) */
  applyNow: (patch: Partial<InferenceConfig>) => Promise<void>;
  /** Reload config from backend */
  refresh: () => Promise<void>;
}

export function useInferenceConfig(): UseInferenceConfigReturn {
  const [config, setConfig] = useState<InferenceConfig>(DEFAULT_INFERENCE_CONFIG);
  const [activeModels, setActiveModels] = useState<ActiveModels | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  // Accumulate pending changes across rapid slider moves
  const pendingPatch = useRef<Partial<InferenceConfig>>({});
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Fetch current config ────────────────────────────────────────────────
  const refresh = useCallback(async () => {
    try {
      setIsLoading(true);
      const [cfgRes, stackRes] = await Promise.all([
        fetch(ENDPOINT),
        fetch(STACK_ENDPOINT),
      ]);

      if (cfgRes.ok) {
        const data: InferenceConfig = await cfgRes.json();
        setConfig(data);
      }
      if (stackRes.ok) {
        const stackData = await stackRes.json();
        if (stackData.models) {
          setActiveModels(stackData.models);
        }
      }
    } catch (err) {
      console.debug("useInferenceConfig: failed to fetch", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // ── Immediate POST ──────────────────────────────────────────────────────
  const applyNow = useCallback(
    async (patch: Partial<InferenceConfig>) => {
      const merged: InferenceConfig = { ...config, ...patch };
      setConfig(merged);
      try {
        setIsSaving(true);
        const res = await fetch(ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(merged),
        });
        if (res.ok) {
          const body = await res.json();
          // Update active models from response if provided
          if (body.active_models) {
            setActiveModels(body.active_models);
          }
          // Sync config from server response to stay consistent
          if (body.config) {
            setConfig(body.config);
          }
        }
      } catch (err) {
        console.error("useInferenceConfig: failed to save", err);
      } finally {
        setIsSaving(false);
      }
    },
    [config],
  );

  // ── Debounced update (for sliders) ──────────────────────────────────────
  const updateConfig = useCallback(
    (patch: Partial<InferenceConfig>) => {
      // Apply optimistically to state immediately for smooth slider UX
      setConfig((prev) => ({ ...prev, ...patch }));
      // Accumulate into pending patch
      pendingPatch.current = { ...pendingPatch.current, ...patch };

      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(async () => {
        const toSend = pendingPatch.current;
        pendingPatch.current = {};
        await applyNow(toSend);
      }, DEBOUNCE_MS);
    },
    [applyNow],
  );

  return { config, activeModels, isLoading, isSaving, updateConfig, applyNow, refresh };
}
