import * as THREE from "three";
import {
  VRM,
  VRMExpressionManager,
  VRMExpressionPresetName,
} from "@pixiv/three-vrm";
import { AutoLookAt } from "./autoLookAt";
import { AutoBlink } from "./autoBlink";
import type { VrmExpressionWeights } from "../vrmViewer/emotionToVrm";

/**
 * VRM Expression Controller with 27D blendshape summation.
 *
 * Instead of a single "dominant" preset, this controller accepts the full
 * VrmExpressionWeights vector from the emotionToVrm mapper and applies
 * every expression simultaneously at its computed weight.
 *
 * Example: Joy 0.8 + Melancholy 0.2 = wistful smile (happy + sad blended).
 */
export class ExpressionController {
  private _autoLookAt: AutoLookAt;
  private _autoBlink?: AutoBlink;
  private _expressionManager?: VRMExpressionManager;
  private _currentEmotion: VRMExpressionPresetName | string;
  private _currentLipSync: {
    preset: VRMExpressionPresetName | string;
    value: number;
  } | null;

  /** Active blendshape weights for lerp smoothing. */
  private _activeWeights: Record<string, number> = {};
  /** Target blendshape weights. */
  private _targetWeights: Record<string, number> = {};

  /** All expression preset names known to the loaded VRM. */
  private static KNOWN_PRESETS = new Set([
    "happy", "angry", "sad", "relaxed", "surprised",
    "aa", "ih", "ou", "ee", "oh",
    "neutral", "blink", "blinkLeft", "blinkRight",
    "lookUp", "lookDown", "lookLeft", "lookRight",
  ]);

  constructor(vrm: VRM, camera: THREE.Object3D) {
    this._autoLookAt = new AutoLookAt(vrm, camera);
    this._currentEmotion = "neutral";
    this._currentLipSync = null;
    this.registerExpression(vrm)
    if (vrm.expressionManager) {
      this._expressionManager = vrm.expressionManager;
      this._autoBlink = new AutoBlink(vrm.expressionManager);
    }
  }

  public registerExpression(vrm: VRM) {
    const expressionManager = vrm.expressionManager;
    if (!expressionManager) return;
  
    const { expressionMap: allExpressions, presetExpressionMap: presetExpressions } = expressionManager;
    const oddExpressions = Object.keys(allExpressions).filter(key => !(key in presetExpressions));
  
    oddExpressions.forEach(expressionName => {
      const expression = allExpressions[expressionName];
      if (expression) expressionManager.registerExpression(expression);
    });

    const allExpressionNames = Object.keys(allExpressions);
    // Register model-specific expressions in the known-presets set.
    allExpressionNames.forEach((name) => ExpressionController.KNOWN_PRESETS.add(name));

    return allExpressionNames;
  }

  /**
   * Legacy single-preset emotion (backward-compatible).
   * For 27D blendshape summation, use applyExpressionWeights() instead.
   */
  public playEmotion(preset: VRMExpressionPresetName | string) {
    const normalizedPreset = `${preset.charAt(0).toUpperCase()}${preset.slice(1)}`;
    
    if (this._currentEmotion == preset) {
      return;
    }

    if (this._currentEmotion != "neutral") {
      this._expressionManager?.setValue(this._currentEmotion, 0);
    }

    if (preset == "neutral") {
      this._autoBlink?.setEnable(true);
      this._currentEmotion = preset;
      // Also zero-out any active blendshape weights
      this._targetWeights = {};
      this._activeWeights = {};
      return;
    }

    const value = (normalizedPreset in VRMExpressionPresetName) ? (normalizedPreset === "Surprised" ? 0.5 : 1) : 0.5;

    const t = this._autoBlink?.setEnable(false) || 0;
    this._currentEmotion = preset;
    setTimeout(() => {
      this._expressionManager?.setValue(preset, value);
    }, t * 1000);
  }

  /**
   * 27D BLENDSHAPE SUMMATION
   *
   * Apply the full weighted expression vector from the emotionToVrm mapper.
   * All 10 VRM presets are set simultaneously at their computed weights,
   * creating emergent facial expressions impossible with single-preset mode.
   *
   * Lerp smoothing prevents jitter between emotion updates.
   */
  /**
   * 27D BLENDSHAPE SUMMATION with SOFT-MAX NORMALIZATION.
   *
   * Prevents vertex distortion by clamping each blendshape weight to [0, 1]
   * and ensuring the sum of all active blendshapes never exceeds 1.0 per
   * morph-target group. This maintains visual structural integrity during
   * high-intensity emotional spikes (e.g., Joy 0.9 + Surprise 0.8).
   *
   * Formula: W_B = min(1.0, Σ(w_i · preset_i,B))
   */
  public applyExpressionWeights(weights: VrmExpressionWeights): void {
    const mgr = this._expressionManager;
    if (!mgr) return;

    // Disable auto blink during active expressions.
    this._autoBlink?.setEnable(false);

    // ---- Soft-Max Normalization -------------------------------------------
    // Clamp each weight to [0, 1] and compute the sum.
    const raw: Record<string, number> = {
      happy: Math.max(0, Math.min(1, weights.happy)),
      angry: Math.max(0, Math.min(1, weights.angry)),
      sad: Math.max(0, Math.min(1, weights.sad)),
      relaxed: Math.max(0, Math.min(1, weights.relaxed)),
      surprised: Math.max(0, Math.min(1, weights.surprised)),
      aa: Math.max(0, Math.min(1, weights.aa)),
      ih: Math.max(0, Math.min(1, weights.ih)),
      ou: Math.max(0, Math.min(1, weights.ou)),
      ee: Math.max(0, Math.min(1, weights.ee)),
      oh: Math.max(0, Math.min(1, weights.oh)),
    };

    // If total blendshape activation exceeds 1.0, proportionally scale down
    // to prevent vertex over-extension.
    const total = Object.values(raw).reduce((a, b) => a + b, 0);
    if (total > 1.0) {
      for (const key of Object.keys(raw)) {
        raw[key] /= total;
      }
    }

    this._targetWeights = raw;

    // Initialize active weights on first call
    if (Object.keys(this._activeWeights).length === 0) {
      this._activeWeights = { ...this._targetWeights };
    }

    // Apply immediately (lerp happens in update())
    for (const [preset, value] of Object.entries(this._activeWeights)) {
      if (ExpressionController.KNOWN_PRESETS.has(preset)) {
        mgr.setValue(preset, value);
      }
    }

    this._currentEmotion = "blended";
  }

  /**
   * Route gaze-related emotion dimensions to AutoLookAt.
   */
  public setGazeEmotion(emotion: {
    curiosity: number;
    fascination: number;
    shame: number;
    trust: number;
    interest: number;
  }): void {
    this._autoLookAt.setEmotionState(emotion);
  }

  /**
   * Reset all expressions to neutral (zero).
   */
  public resetExpressions(): void {
    const mgr = this._expressionManager;
    if (!mgr) return;

    for (const preset of ExpressionController.KNOWN_PRESETS) {
      mgr.setValue(preset, 0);
    }

    this._activeWeights = {};
    this._targetWeights = {};
    this._currentEmotion = "neutral";
    this._autoBlink?.setEnable(true);
  }

  public lipSync(preset: VRMExpressionPresetName | string, value: number) {
    if (this._currentLipSync) {
      this._expressionManager?.setValue(this._currentLipSync.preset, 0);
    }
    this._currentLipSync = {
      preset,
      value,
    };
  }

  public update(delta: number) {
    // Micro-saccades & gaze offset (runs every frame)
    this._autoLookAt.update(delta);

    if (this._autoBlink) {
      this._autoBlink.update(delta);
    }

    // Lerp blendshape weights toward target
    const lerpFactor = Math.min(1, delta * 8); // ~8 lerp-units per second
    for (const key of Object.keys(this._targetWeights)) {
      const cur = this._activeWeights[key] ?? 0;
      const tgt = this._targetWeights[key] ?? 0;
      this._activeWeights[key] = cur + (tgt - cur) * lerpFactor;
    }

    // Apply lerped weights every frame
    if (this._currentEmotion === "blended") {
      const mgr = this._expressionManager;
      if (mgr) {
        for (const [preset, value] of Object.entries(this._activeWeights)) {
          if (ExpressionController.KNOWN_PRESETS.has(preset)) {
            mgr.setValue(preset, value);
          }
        }
      }
    }

    if (this._currentLipSync) {
      const weight =
        this._currentEmotion === "neutral"
          ? this._currentLipSync.value * 0.5
          : this._currentLipSync.value * 0.25;
      this._expressionManager?.setValue(this._currentLipSync.preset, weight);
    }
  }
}


