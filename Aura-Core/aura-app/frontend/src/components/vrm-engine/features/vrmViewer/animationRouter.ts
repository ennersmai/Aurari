/**
 * AnimationRouter — The "Reflex Layer" + L5 Animation Selector
 *
 * Maps the full 27D emotion vector to VRMA animation triggers.
 * Uses magnitude-threshold logic with cooldowns (no maxPlays limits —
 * animations should feel alive and responsive, not exhaustible).
 *
 * NEW: L5 Animation Selector — when the backend L5 model is available,
 * it can override the reflex-based selection with a semantically-aware
 * animation choice based on the conversation context. The fast route
 * L1→L5 bypasses L2/L3 for sub-500ms animation selection.
 *
 * NEW: Movement Command Layer — explicit user commands ("wave", "dance",
 * "spin") are routed via setDirectOverride(), which bypasses ALL cooldowns
 * and cooldown timers for an instant response.
 *
 * Animations are preloaded and cached so they play instantly on trigger.
 */

import type { EmotionState } from "@/types/aura";
import { loadVRMAnimation } from "../../lib/VRMAnimation/loadVRMAnimation";
import type { VRMAnimation } from "../../lib/VRMAnimation/VRMAnimation";

// ---- Animation registry ------------------------------------------------

/** Maps animation file names to their trigger conditions. */
interface AnimationRule {
  file: string;
  /** Emotion dimension thresholds (all must be met). */
  conditions: Partial<Record<keyof EmotionState, number>>;
  /** Minimum cooldown between triggers (ms). */
  cooldownMs: number;
  /** Human-readable description. */
  description: string;
  /** Priority (higher = checked first). */
  priority: number;
}

/**
 * Movement keyword → animation file mapping.
 * Used by setMovementCommand() for instant response to explicit user requests.
 * Keywords are matched case-insensitively against the user's message.
 */
export const MOVEMENT_KEYWORD_MAP: Record<string, string> = {
  // Greeting variants
  "wave":               "/vrm-assets/greeting.vrma",
  "wave hello":         "/vrm-assets/greeting_enthusiastic.vrma",
  "wave at me":         "/vrm-assets/greeting_enthusiastic.vrma",
  "say hello":          "/vrm-assets/greeting.vrma",
  "say hi":             "/vrm-assets/greeting.vrma",
  "hello":              "/vrm-assets/hello.vrma",
  "greet":              "/vrm-assets/greeting.vrma",
  "bow":                "/vrm-assets/greeting_shy.vrma",
  "curtsy":             "/vrm-assets/greeting_shy.vrma",

  // Dance variants
  "dance":              "/vrm-assets/dance.vrma",
  "dance for me":       "/vrm-assets/dance.vrma",
  "do a dance":         "/vrm-assets/dance.vrma",
  "dance fast":         "/vrm-assets/dance_fast.vrma",
  "dance slow":         "/vrm-assets/dance_slow.vrma",
  "sway":               "/vrm-assets/dance_subtle.vrma",

  // Spin variants
  "spin":               "/vrm-assets/spin.vrma",
  "turn around":        "/vrm-assets/spin.vrma",
  "spin around":        "/vrm-assets/spin.vrma",
  "twirl":              "/vrm-assets/spin_slow.vrma",
  "spin fast":          "/vrm-assets/spin_fast.vrma",

  // Peace sign
  "peace":              "/vrm-assets/peaceSign.vrma",
  "peace sign":         "/vrm-assets/peaceSign.vrma",
  "peace out":          "/vrm-assets/peaceSign_double.vrma",
  "v sign":             "/vrm-assets/peaceSign.vrma",

  // Pose
  "pose":               "/vrm-assets/modelPose.vrma",
  "model":              "/vrm-assets/modelPose_confident.vrma",
  "model pose":         "/vrm-assets/modelPose_confident.vrma",
  "strike a pose":      "/vrm-assets/modelPose_confident.vrma",
  "show yourself":      "/vrm-assets/showFullBody.vrma",
  "show me you":        "/vrm-assets/showFullBody.vrma",
  "full body":          "/vrm-assets/showFullBody_confident.vrma",

  // Idle
  "stand still":        "/vrm-assets/idle_loop.vrma",
  "relax":              "/vrm-assets/idle_relaxed.vrma",
  "be idle":            "/vrm-assets/idle_loop.vrma",

  // Squat / crouch
  "squat":              "/vrm-assets/squat.vrma",
  "crouch":             "/vrm-assets/squat_quick.vrma",
  "sit down":           "/vrm-assets/squat_deep.vrma",

  // New animations from GitHub pack
  "motion pose":        "/vrm-assets/motion_pose.vrma",
};

/**
 * 27D Emotion → Animation mapping.
 *
 * Each rule maps specific emotion combinations to VRMA animations.
 * NO maxPlays limits — animations are reactive, not consumable.
 * Cooldowns prevent spam but allow repeated triggering.
 *
 * Global cooldown lowered to 3s; per-rule cooldowns reduced for responsiveness.
 */
const ANIMATION_RULES: AnimationRule[] = [
  // ---- HIGH ENERGY / POSITIVE ----
  {
    file: "/vrm-assets/dance.vrma",
    conditions: { joy: 0.55, arousal: 0.5 },
    cooldownMs: 25_000,
    priority: 10,
    description: "Joyful + energetic → happy dance",
  },
  {
    file: "/vrm-assets/dance_fast.vrma",
    conditions: { joy: 0.7, arousal: 0.65 },
    cooldownMs: 22_000,
    priority: 11,
    description: "Very joyful + high energy → fast energetic dance",
  },
  {
    file: "/vrm-assets/dance_slow.vrma",
    conditions: { joy: 0.4, serenity: 0.4 },
    cooldownMs: 28_000,
    priority: 8,
    description: "Gentle joy + serene → slow graceful dance",
  },
  {
    file: "/vrm-assets/dance_subtle.vrma",
    conditions: { joy: 0.3, interest: 0.35 },
    cooldownMs: 18_000,
    priority: 7,
    description: "Mild joy + interest → subtle sway",
  },
  {
    file: "/vrm-assets/spin.vrma",
    conditions: { surprise: 0.5, wonder: 0.4 },
    cooldownMs: 15_000,
    priority: 9,
    description: "Surprised + wondering → spin around",
  },
  {
    file: "/vrm-assets/spin_fast.vrma",
    conditions: { surprise: 0.7, fascination: 0.5 },
    cooldownMs: 15_000,
    priority: 10,
    description: "Very surprised + fascinated → rapid spin",
  },
  {
    file: "/vrm-assets/spin_slow.vrma",
    conditions: { wonder: 0.5, serenity: 0.35 },
    cooldownMs: 20_000,
    priority: 7,
    description: "Wondering + serene → slow dreamy spin",
  },
  {
    file: "/vrm-assets/greeting.vrma",
    conditions: { trust: 0.5, interest: 0.4 },
    cooldownMs: 45_000,
    priority: 8,
    description: "Trusting + interested → wave hello",
  },
  {
    file: "/vrm-assets/greeting_enthusiastic.vrma",
    conditions: { joy: 0.6, trust: 0.5 },
    cooldownMs: 35_000,
    priority: 9,
    description: "Joyful + trusting → enthusiastic wave",
  },
  {
    file: "/vrm-assets/greeting_shy.vrma",
    conditions: { trust: 0.35, shame: 0.3 },
    cooldownMs: 25_000,
    priority: 6,
    description: "Shy + tentative trust → timid wave",
  },
  {
    file: "/vrm-assets/greeting_left.vrma",
    conditions: { trust: 0.5, curiosity: 0.4 },
    cooldownMs: 30_000,
    priority: 7,
    description: "Trusting + curious → left-handed wave",
  },

  // ---- SOCIAL / WARM ----
  {
    file: "/vrm-assets/peaceSign.vrma",
    conditions: { serenity: 0.45, trust: 0.35 },
    cooldownMs: 22_000,
    priority: 7,
    description: "Serene + trusting → peace sign",
  },
  {
    file: "/vrm-assets/peaceSign_double.vrma",
    conditions: { joy: 0.55, serenity: 0.4 },
    cooldownMs: 20_000,
    priority: 8,
    description: "Joyful + serene → double peace sign",
  },
  {
    file: "/vrm-assets/peaceSign_slow.vrma",
    conditions: { serenity: 0.6, gratitude: 0.4 },
    cooldownMs: 25_000,
    priority: 7,
    description: "Deeply serene + grateful → slow graceful peace",
  },
  {
    file: "/vrm-assets/modelPose.vrma",
    conditions: { curiosity: 0.55, interest: 0.45 },
    cooldownMs: 18_000,
    priority: 7,
    description: "Curious + interested → lean in / model pose",
  },
  {
    file: "/vrm-assets/modelPose_confident.vrma",
    conditions: { certainty: 0.55, pride: 0.4 },
    cooldownMs: 18_000,
    priority: 8,
    description: "Certain + proud → confident model pose",
  },
  {
    file: "/vrm-assets/modelPose_shy.vrma",
    conditions: { curiosity: 0.4, shame: 0.3 },
    cooldownMs: 20_000,
    priority: 6,
    description: "Curious but shy → hesitant pose",
  },

  // ---- COGNITIVE / THINKING ----
  {
    file: "/vrm-assets/showFullBody.vrma",
    conditions: { confusion: 0.4, doubt: 0.35 },
    cooldownMs: 15_000,
    priority: 6,
    description: "Confused + doubtful → defensive stance",
  },
  {
    file: "/vrm-assets/showFullBody_confident.vrma",
    conditions: { pride: 0.55, certainty: 0.4 },
    cooldownMs: 18_000,
    priority: 7,
    description: "Proud + certain → confident full body display",
  },
  {
    file: "/vrm-assets/squat.vrma",
    conditions: { sadness: 0.45, melancholy: 0.4 },
    cooldownMs: 20_000,
    priority: 6,
    description: "Sad + melancholic → squat (dejected)",
  },
  {
    file: "/vrm-assets/squat_deep.vrma",
    conditions: { sadness: 0.65, boredom: 0.4 },
    cooldownMs: 22_000,
    priority: 6,
    description: "Very sad + bored → deep dejected squat",
  },
  {
    file: "/vrm-assets/squat_quick.vrma",
    conditions: { fear: 0.5, surprise: 0.4 },
    cooldownMs: 12_000,
    priority: 7,
    description: "Fearful + surprised → quick crouch",
  },

  // ---- INTENSE / NEGATIVE ----
  {
    file: "/vrm-assets/shoot.vrma",
    conditions: { anger: 0.55, disgust: 0.3 },
    cooldownMs: 12_000,
    priority: 5,
    description: "Angry + disgusted → shooting gesture",
  },
  {
    file: "/vrm-assets/shoot_double.vrma",
    conditions: { anger: 0.7, arousal: 0.6 },
    cooldownMs: 12_000,
    priority: 6,
    description: "Very angry + high energy → double shoot",
  },

  // ---- AESTHETIC / DEEP ----
  {
    file: "/vrm-assets/greeting.vrma",
    conditions: { awe: 0.6, beauty: 0.4 },
    cooldownMs: 30_000,
    priority: 8,
    description: "Awe + beauty → reverent greeting",
  },
  {
    file: "/vrm-assets/spin.vrma",
    conditions: { fascination: 0.6, curiosity: 0.4 },
    cooldownMs: 18_000,
    priority: 9,
    description: "Fascinated + curious → excited spin",
  },

  // ---- SOCIAL BONDING ----
  {
    file: "/vrm-assets/peaceSign.vrma",
    conditions: { empathy: 0.55, compassion: 0.45 },
    cooldownMs: 20_000,
    priority: 7,
    description: "Empathetic + compassionate → peace sign",
  },
  {
    file: "/vrm-assets/greeting.vrma",
    conditions: { gratitude: 0.5, love: 0.4 },
    cooldownMs: 30_000,
    priority: 8,
    description: "Grateful + loving → warm greeting",
  },

  // ---- LOW ENERGY / REFLECTIVE ----
  {
    file: "/vrm-assets/modelPose.vrma",
    conditions: { nostalgia: 0.5, serenity: 0.35 },
    cooldownMs: 20_000,
    priority: 6,
    description: "Nostalgic + serene → reflective pose",
  },
  {
    file: "/vrm-assets/squat.vrma",
    conditions: { boredom: 0.5, arousal: 0.25 },
    cooldownMs: 25_000,
    priority: 5,
    description: "Bored + low energy → squat",
  },

  // ---- FEAR / ANXIETY ----
  {
    file: "/vrm-assets/showFullBody.vrma",
    conditions: { fear: 0.5, confusion: 0.35 },
    cooldownMs: 15_000,
    priority: 6,
    description: "Fearful + confused → defensive stance",
  },

  // ---- PRIDE / CONFIDENCE ----
  {
    file: "/vrm-assets/dance.vrma",
    conditions: { pride: 0.5, certainty: 0.45 },
    cooldownMs: 25_000,
    priority: 8,
    description: "Proud + certain → confident dance",
  },

  // ---- IDLE VARIATIONS (low threshold, frequent) ----
  {
    file: "/vrm-assets/idle_energetic.vrma",
    conditions: { arousal: 0.45, joy: 0.3 },
    cooldownMs: 10_000,
    priority: 4,
    description: "Moderate energy + mild joy → energetic idle",
  },
  {
    file: "/vrm-assets/idle_relaxed.vrma",
    conditions: { serenity: 0.4, arousal: 0.25 },
    cooldownMs: 12_000,
    priority: 4,
    description: "Serene + low energy → relaxed idle",
  },
  {
    file: "/vrm-assets/idle_curious.vrma",
    conditions: { curiosity: 0.4, interest: 0.35 },
    cooldownMs: 10_000,
    priority: 4,
    description: "Curious + interested → curious leaning idle",
  },
];

// ---- L5 Animation Selector Types ---------------------------------------

export interface L5AnimationRequest {
  /** The 27D emotion vector. */
  emotion: EmotionState;
  /** Recent conversation context (last few messages). */
  context?: string[];
  /** The text about to be spoken (for semantic alignment). */
  upcomingText?: string;
}

export interface L5AnimationResponse {
  /** Selected animation file path. */
  animation: string;
  /** Confidence [0, 1]. */
  confidence: number;
  /** Human-readable reasoning. */
  reasoning: string;
}

// ---- Router -------------------------------------------------------------

export interface AnimationRouteResult {
  /** The VRMAnimation to play, or null if no rule matched. */
  animation: VRMAnimation | null;
  /** Name of the matched rule (for logging). */
  rule: string;
  /** The VRMA file path (e.g. "/vrm-assets/dance.vrma") for position offsets. */
  file: string;
}

export class AnimationRouter {
  /** Cache: file path → parsed VRMAnimation. */
  private cache = new Map<string, VRMAnimation>();
  /** Per-rule last-triggered timestamps (ms). */
  private cooldowns = new Map<string, number>();
  /** L5 override: if set, skip reflex routing and use this animation. */
  private l5Override: { file: string; until: number } | null = null;
  /**
   * Direct override: movement command bypass — takes priority over L5 and reflex.
   * Bypasses ALL cooldowns including global.
   */
  private directOverride: { file: string; until: number } | null = null;
  /** Track the last played animation to avoid immediate repeats. */
  private lastPlayed: string | null = null;
  /**
   * Minimum interval between ANY reflex-triggered animation (global cooldown).
   * Lowered from 8s → 3s for more responsiveness.
   */
  private globalCooldownMs = 3000;
  private lastGlobalTrigger = 0;

  /**
   * Evaluate the 27D emotion vector against all animation rules.
   * Returns the highest-priority matching animation, respecting cooldowns.
   *
   * Priority order:
   *   1. Direct override (movement command — bypasses all cooldowns)
   *   2. L5 override (semantically-selected animation)
   *   3. Reflex rules (emotion-threshold matching)
   */
  async route(emotion: EmotionState): Promise<AnimationRouteResult> {
    const now = Date.now();

    // ---- Priority 1: Direct override (movement command — no cooldown) ----
    if (this.directOverride && now < this.directOverride.until) {
      const file = this.directOverride.file;
      this.directOverride = null; // consume once
      const animation = await this.loadAnimation(file);
      if (animation) {
        this.lastGlobalTrigger = now;
        this.lastPlayed = file;
        console.log(`[AnimationRouter] Direct movement command: ${file}`);
        return { animation, rule: "direct_command", file };
      }
    }

    // ---- Global cooldown: prevent animation spam ----
    if (now - this.lastGlobalTrigger < this.globalCooldownMs) {
      return { animation: null, rule: "global_cooldown", file: "" };
    }

    // ---- Priority 2: L5 Override — semantically-selected animation ----
    if (this.l5Override && now < this.l5Override.until) {
      const file = this.l5Override.file;
      const animation = await this.loadAnimation(file);
      if (animation) {
        this.lastGlobalTrigger = now;
        this.lastPlayed = file;
        console.log(`[AnimationRouter] L5 Override: ${file}`);
        return { animation, rule: "L5_override", file };
      }
      // If L5 animation failed to load, clear override and fall through
      this.l5Override = null;
    }

    // ---- Priority 3: Reflex rules ----
    const sortedRules = [...ANIMATION_RULES].sort((a, b) => b.priority - a.priority);

    for (const rule of sortedRules) {
      // Check cooldown
      const lastTriggered = this.cooldowns.get(rule.file) ?? 0;
      if (now - lastTriggered < rule.cooldownMs) {
        continue;
      }

      // Avoid immediate repeat of the same animation
      if (rule.file === this.lastPlayed && now - lastTriggered < rule.cooldownMs * 2) {
        continue;
      }

      // Check all conditions
      const matched = Object.entries(rule.conditions).every(([dim, threshold]) => {
        const value = (emotion as unknown as Record<string, number>)[dim] ?? 0;
        return value >= threshold;
      });

      if (matched) {
        this.cooldowns.set(rule.file, now);
        this.lastGlobalTrigger = now;
        this.lastPlayed = rule.file;
        const animation = await this.loadAnimation(rule.file);
        if (animation) {
          console.log(
            `[AnimationRouter] Reflex: ${rule.description} → ${rule.file.split("/").pop()}`
          );
        }
        return { animation, rule: rule.description, file: rule.file };
      }
    }

    return { animation: null, rule: "no_match", file: "" };
  }

  /**
   * Set an L5 animation override.
   *
   * Called when the backend L5 model selects an animation based on
   * conversation semantics. The override lasts for `durationMs` or until
   * the animation plays once.
   */
  setL5Override(file: string, durationMs: number = 12000): void {
    this.l5Override = { file, until: Date.now() + durationMs };
    console.log(`[AnimationRouter] L5 override set: ${file} (valid for ${durationMs}ms)`);
  }

  /** Clear any active L5 override. */
  clearL5Override(): void {
    this.l5Override = null;
  }

  /**
   * Set a direct movement command override.
   *
   * Called when the user explicitly requests a movement (e.g. "wave at me",
   * "do a spin"). Bypasses ALL cooldowns — instant response, plays once.
   *
   * @param file   VRMA file path (e.g. "/vrm-assets/greeting.vrma")
   * @param durationMs How long the override stays active (default 10s)
   */
  setDirectOverride(file: string, durationMs: number = 10000): void {
    this.directOverride = { file, until: Date.now() + durationMs };
    console.log(`[AnimationRouter] Direct override set: ${file}`);
  }

  /**
   * Detect movement keywords in a user message and set a direct override.
   * Returns the matched animation file, or null if no keyword matched.
   */
  detectAndSetMovementCommand(message: string): string | null {
    const lower = message.toLowerCase();

    // Sort by length descending so longer phrases match before shorter ones
    const sortedKeywords = Object.keys(MOVEMENT_KEYWORD_MAP).sort((a, b) => b.length - a.length);

    for (const keyword of sortedKeywords) {
      if (lower.includes(keyword)) {
        const file = MOVEMENT_KEYWORD_MAP[keyword];
        this.setDirectOverride(file);
        return file;
      }
    }

    return null;
  }

  /** Load (or retrieve from cache) a VRMA animation. */
  private async loadAnimation(file: string): Promise<VRMAnimation | null> {
    const cached = this.cache.get(file);
    if (cached) return cached;

    try {
      const animation = await loadVRMAnimation(file);
      if (animation) {
        this.cache.set(file, animation);
      }
      return animation;
    } catch (e) {
      console.warn(`[AnimationRouter] Failed to load ${file}:`, e);
      return null;
    }
  }

  /** Reset all cooldowns (useful when session restarts). */
  resetCooldowns(): void {
    this.cooldowns.clear();
    this.l5Override = null;
    this.directOverride = null;
    this.lastPlayed = null;
    this.lastGlobalTrigger = 0;
  }

  /**
   * Get the list of all available animation files.
   * Useful for the L5 selector to know what's available.
   */
  static getAvailableAnimations(): string[] {
    const files = new Set(ANIMATION_RULES.map((r) => r.file));
    return [...files];
  }
}
