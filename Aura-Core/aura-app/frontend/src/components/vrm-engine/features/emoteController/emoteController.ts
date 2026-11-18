import * as THREE from "three";
import { VRM, VRMExpressionPresetName } from "@pixiv/three-vrm";
import { ExpressionController } from "./expressionController";
import type { VrmExpressionWeights } from "../vrmViewer/emotionToVrm";
import type { ProceduralAnimation } from "../proceduralAnimation/proceduralAnimation";

/**
 * EmoteController — the biological orchestration layer.
 *
 * Bridges the 27D emotion vector to:
 * - ExpressionController (facial blendshapes)
 * - AutoLookAt (micro-saccades, gaze offset)
 * - ProceduralAnimation (breath, idle micro-motion)
 */
export class EmoteController {
  private _expressionController: ExpressionController;
  private _proceduralAnimation: ProceduralAnimation | null;

  constructor(vrm: VRM, camera: THREE.Object3D, proceduralAnimation?: ProceduralAnimation) {
    this._expressionController = new ExpressionController(vrm, camera);
    this._proceduralAnimation = proceduralAnimation ?? null;
  }

  /**
   * Push the full 27D emotion vector to all biological subsystems.
   * Called by AuraAvatar on every emotion_update from the WebSocket.
   */
  public setEmotionState(emotion: {
    // Needed by ProceduralAnimation (breath)
    arousal: number;
    serenity: number;
    // Needed by AutoLookAt (gaze)
    curiosity: number;
    fascination: number;
    shame: number;
    trust: number;
    interest: number;
  }): void {
    this._expressionController.setGazeEmotion(emotion);
    this._proceduralAnimation?.setEmotionState({
      arousal: emotion.arousal,
      serenity: emotion.serenity,
    });
  }

  /** Legacy single-preset emotion. */
  public playEmotion(preset: VRMExpressionPresetName | string) {
    this._expressionController.playEmotion(preset);
  }

  /** 27D blendshape summation. */
  public applyExpressionWeights(weights: VrmExpressionWeights) {
    this._expressionController.applyExpressionWeights(weights);
  }

  /** Reset all expressions to neutral. */
  public resetExpressions() {
    this._expressionController.resetExpressions();
  }

  public lipSync(preset: VRMExpressionPresetName | string, value: number) {
    this._expressionController.lipSync(preset, value);
  }

  /**
   * Per-frame update. Delegates to ExpressionController (blink, lip-sync lerp)
   * and AutoLookAt (micro-saccades). ProceduralAnimation is updated by Model.
   */
  public update(delta: number) {
    this._expressionController.update(delta);
  }
}
