import * as THREE from "three";
import { VRM } from "@pixiv/three-vrm";

/**
 * Biological Gaze Controller with Micro-Saccades & Emotional Offset.
 *
 * Humans never stare perfectly still — their eyes make tiny, jittery
 * movements (micro-saccades). This controller adds:
 *
 * 1. **Micro-Saccades**: Tiny random jitter on the lookAt target.
 *    - High curiosity/fascination → narrow jitter radius (focused).
 *    - High shame/hesitation → wide jitter radius (avoidant, erratic).
 *
 * 2. **Emotional Gaze Offset**: The lookAt target is offset based on emotion.
 *    - High shame/embarrassment → look away by 15-20° downward.
 *    - High trust/interest → direct eye contact (centered on camera).
 *
 * 3. **Smooth Pursuit**: Lerp toward target position for natural eye movement.
 */
export class AutoLookAt {
  private _lookAtTarget: THREE.Object3D;
  private _camera: THREE.Object3D;
  private _vrm: VRM;

  /** Accumulated time for saccade waveform generation. */
  private _saccadeTime: number = 0;

  // ---- Emotion-driven parameters ----------------------------------------
  /** Saccade radius in world units (0 = no jitter, 0.02 = wide jitter). */
  private _saccadeRadius: number = 0.003;
  /** Gaze offset angle in radians (0 = direct eye contact). */
  private _gazeOffsetY: number = 0;   // vertical offset
  private _gazeOffsetX: number = 0;   // horizontal offset
  /** Current saccade offset (smoothed). */
  private _currentSaccadeX: number = 0;
  private _currentSaccadeY: number = 0;
  /** Target saccade offset (randomly updated). */
  private _targetSaccadeX: number = 0;
  private _targetSaccadeY: number = 0;
  /** Time until next saccade update. */
  private _saccadeTimer: number = 0;

  /** Base position of the lookAt target relative to camera. */
  private _basePosition: THREE.Vector3;

  constructor(vrm: VRM, camera: THREE.Object3D) {
    this._vrm = vrm;
    this._camera = camera;
    this._lookAtTarget = new THREE.Object3D();
    this._basePosition = new THREE.Vector3(0, 0, -1);
    this._lookAtTarget.position.copy(this._basePosition);
    camera.add(this._lookAtTarget);

    if (vrm.lookAt) vrm.lookAt.target = this._lookAtTarget;
  }

  /**
   * Update gaze parameters from the 27D emotion vector.
   * Called by AuraAvatar on every emotion update.
   */
  public setEmotionState(emotion: {
    curiosity: number;
    fascination: number;
    shame: number;
    trust: number;
    interest: number;
  }): void {
    const curiosity = emotion.curiosity ?? 0;
    const fascination = emotion.fascination ?? 0;
    const shame = emotion.shame ?? 0;
    const trust = emotion.trust ?? 0;
    const interest = emotion.interest ?? 0;

    // Saccade radius: high focus → narrow jitter; high shame → wide, erratic jitter
    const focusIntensity = Math.max(curiosity, fascination);
    const avoidance = shame;
    this._saccadeRadius = 0.001 + avoidance * 0.02 - focusIntensity * 0.001;
    this._saccadeRadius = Math.max(0.0005, this._saccadeRadius);

    // Gaze offset: shame makes her look down and away
    this._gazeOffsetY = -shame * 0.3;  // down by up to ~17°
    this._gazeOffsetX = shame * 0.15 * (Math.random() > 0.5 ? 1 : -1);  // slightly to one side

    // Trust + interest → direct eye contact (center the gaze)
    const directness = Math.max(trust, interest) * 0.5;
    this._gazeOffsetY *= (1 - directness);
    this._gazeOffsetX *= (1 - directness);
  }

  /**
   * Update the lookAt target with micro-saccades and emotional offset.
   * Call every frame from the animation loop.
   */
  public update(delta: number): void {
    this._saccadeTime += delta;

    // ---- Micro-Saccade Generation ---------------------------------------
    // Randomly pick a new saccade target every 80-200ms (human-like).
    this._saccadeTimer -= delta;
    if (this._saccadeTimer <= 0) {
      // Random point within saccade radius
      const angle = Math.random() * 2 * Math.PI;
      const radius = Math.random() * this._saccadeRadius;
      this._targetSaccadeX = Math.cos(angle) * radius;
      this._targetSaccadeY = Math.sin(angle) * radius;

      // Humans hold a fixation for 80-300ms, then jump (saccade)
      this._saccadeTimer = 0.08 + Math.random() * 0.22;
    }

    // Lerp toward saccade target (fast — saccades are ballistic)
    const saccadeSpeed = 15; // lerp units per second
    const lerpFactor = Math.min(1, delta * saccadeSpeed);
    this._currentSaccadeX += (this._targetSaccadeX - this._currentSaccadeX) * lerpFactor;
    this._currentSaccadeY += (this._targetSaccadeY - this._currentSaccadeY) * lerpFactor;

    // ---- Apply to lookAt target -----------------------------------------
    this._lookAtTarget.position.set(
      this._basePosition.x + this._gazeOffsetX + this._currentSaccadeX,
      this._basePosition.y + this._gazeOffsetY + this._currentSaccadeY,
      this._basePosition.z,
    );
  }

  /** Clean up the lookAt target object. */
  public dispose(): void {
    this._camera.remove(this._lookAtTarget);
    if (this._vrm.lookAt) {
      this._vrm.lookAt.target = null;
    }
  }
}
