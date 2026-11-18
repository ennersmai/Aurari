/**
 * 27D Emotion Vector → VRM Blendshape Translation Matrix
 *
 * Maps Aura's full 27-dimensional emotional state to standard VRM 1.0
 * expression presets AND individual blendshape weights. Uses weighted
 * activation functions for smooth, believable facial animation.
 *
 * VRM 1.0 Standard Expressions:
 *   happy, angry, sad, relaxed, surprised, aa, ih, ou, ee, oh,
 *   blink, blinkLeft, blinkRight, lookUp, lookDown, lookLeft,
 *   lookRight, neutral
 *
 * Architecture:
 *   - Primary emotion-to-expression mapping (weighted sum)
 *   - Procedural blink generation (periodic + emotion-modulated rate)
 *   - Eye gaze synthesis from cognitive emotions (curiosity → lookAround)
 *   - Arousal-modulated expression intensity scaling
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Full 27-dimension emotion vector from the backend. */
export interface EmotionVector27D {
  // Primary (9)
  love: number; joy: number; interest: number; trust: number;
  fear: number; sadness: number; anger: number; surprise: number;
  disgust: number;
  // Aesthetic (6)
  awe: number; beauty: number; wonder: number; serenity: number;
  melancholy: number; nostalgia: number;
  // Social (6)
  empathy: number; gratitude: number; pride: number; shame: number;
  envy: number; compassion: number;
  // Cognitive (6)
  curiosity: number; confusion: number; certainty: number; doubt: number;
  fascination: number; boredom: number;
}

/** Standard VRM 1.0 expression weight (0.0–1.0). */
export interface VrmBlendshapeWeights {
  happy: number;
  angry: number;
  sad: number;
  relaxed: number;
  surprised: number;
  aa: number;
  ih: number;
  ou: number;
  ee: number;
  oh: number;
  blink: number;
  blinkLeft: number;
  blinkRight: number;
  lookUp: number;
  lookDown: number;
  lookLeft: number;
  lookRight: number;
  neutral: number;
}

/** Emotion stream message from the WebSocket. */
export interface EmotionStreamMessage {
  type: "emotion_vector";
  timestamp: string;
  vector: EmotionVector27D;
  dominant: string;
  dominant_intensity: number;
  valence: number;
  arousal: number;
  volatility: number;
  description: string;
}

// ---------------------------------------------------------------------------
// Weight Matrix  (27D emotion → VRM expression contribution)
// ---------------------------------------------------------------------------

const WEIGHTS: Record<string, Partial<Record<keyof EmotionVector27D, number>>> = {
  happy: {
    joy: 1.0, love: 0.4, gratitude: 0.3, serenity: 0.2, pride: 0.3,
    interest: 0.2, trust: 0.1, certainty: 0.1, compassion: 0.2,
  },
  angry: {
    anger: 1.0, disgust: 0.5, fear: 0.2, envy: 0.4, shame: 0.1,
    doubt: 0.2,
  },
  sad: {
    sadness: 1.0, melancholy: 0.7, nostalgia: 0.4,
    fear: 0.3, shame: 0.2, boredom: 0.2,
  },
  relaxed: {
    serenity: 1.0, trust: 0.5, love: 0.3, gratitude: 0.3, beauty: 0.4,
    awe: 0.2, compassion: 0.2,
  },
  surprised: {
    surprise: 1.0, awe: 0.7, wonder: 0.6, fascination: 0.4, curiosity: 0.3,
    fear: 0.3, confusion: 0.2,
  },
  // Viseme-like expressions — primarily TTS-driven, but emotion-modulated
  aa: { surprise: 0.8, awe: 0.5, wonder: 0.4 },
  ih: { interest: 0.6, curiosity: 0.7, confusion: 0.3, doubt: 0.2 },
  ou: { sadness: 0.4, melancholy: 0.6, boredom: 0.3 },
  ee: { joy: 0.7, love: 0.3 },
  oh: { surprise: 0.5, awe: 0.6, wonder: 0.5 },
};

// ---------------------------------------------------------------------------
// Blink state machine (procedural, emotion-modulated)
// ---------------------------------------------------------------------------

interface BlinkState {
  isBlinking: boolean;
  progress: number;      // 0 → 1 (close) → 0 (open)
  timeSinceLastBlink: number;
  nextBlinkInterval: number;
  closeSpeed: number;
  openSpeed: number;
}

let _blinkState: BlinkState = {
  isBlinking: false,
  progress: 0,
  timeSinceLastBlink: 0,
  nextBlinkInterval: 3.0 + Math.random() * 4.0,  // 3-7 seconds
  closeSpeed: 0.15,
  openSpeed: 0.08,
};

/**
 * Update the blink state machine.
 *
 * Call once per frame with deltaTime (seconds).
 * Returns the current blink weight (0 = open, 1 = closed).
 */
export function updateBlink(deltaTime: number, arousal: number = 0.5): number {
  const s = _blinkState;

  // Arousal modulates blink rate: high arousal → faster blinking
  const arousalMultiplier = 0.5 + arousal * 0.5;  // 0.5–1.0

  s.timeSinceLastBlink += deltaTime;

  if (!s.isBlinking && s.timeSinceLastBlink >= s.nextBlinkInterval * arousalMultiplier) {
    // Start a blink
    s.isBlinking = true;
    s.progress = 0;
  }

  if (s.isBlinking) {
    // Progress goes 0 → 1 (closing), then 1 → 0 (opening)
    if (s.progress < 1.0) {
      s.progress = Math.min(1.0, s.progress + s.closeSpeed);
    } else {
      s.progress = Math.max(0.0, s.progress - s.openSpeed);
    }

    if (s.progress <= 0.0) {
      s.isBlinking = false;
      s.progress = 0;
      s.timeSinceLastBlink = 0;
      s.nextBlinkInterval = 3.0 + Math.random() * 4.0;  // reset interval
    }

    // Quadratic easing for natural feel
    const t = s.progress < 0.5
      ? 2 * s.progress * s.progress
      : 1 - Math.pow(-2 * s.progress + 2, 2) / 2;
    return t;
  }

  return 0.0;
}

// ---------------------------------------------------------------------------
// Eye gaze synthesis
// ---------------------------------------------------------------------------

/**
 * Compute eye look direction weights from cognitive emotion dimensions.
 *
 * - High curiosity + interest → look around more
 * - High boredom → look down
 * - High certainty → centered gaze
 * - High confusion → look around erratically
 */
export function computeGaze(vector: EmotionVector27D): {
  lookUp: number;
  lookDown: number;
  lookLeft: number;
  lookRight: number;
} {
  const curiosity = vector.curiosity + vector.interest + vector.fascination;
  const lookAround = Math.min(1.0, curiosity / 3.0);

  // Oscillating gaze direction using a slow sine wave
  const t = Date.now() / 3000;  // 3-second cycle
  const gazeX = Math.sin(t * 1.7) * lookAround * 0.6;
  const gazeY = Math.cos(t * 1.3) * lookAround * 0.3;

  // Boredom pulls gaze down
  const boredomDown = vector.boredom * 0.4;

  return {
    lookUp: Math.max(0, gazeY),
    lookDown: Math.max(0, -gazeY + boredomDown),
    lookLeft: Math.max(0, gazeX),
    lookRight: Math.max(0, -gazeX),
  };
}

// ---------------------------------------------------------------------------
// Core translation function
// ---------------------------------------------------------------------------

/** Internal lerp state for smooth transitions. */
class ExpressionLerp {
  current: Record<string, number> = {};
  target: Record<string, number> = {};
  factor: number;

  constructor(factor: number = 0.08) {
    this.factor = factor;
  }

  setTarget(weights: Record<string, number>): void {
    this.target = { ...weights };
    if (Object.keys(this.current).length === 0) {
      this.current = { ...weights };
    }
  }

  tick(): Record<string, number> {
    for (const key of Object.keys(this.target)) {
      const cur = this.current[key] ?? 0;
      const tgt = this.target[key] ?? 0;
      this.current[key] = cur + (tgt - cur) * this.factor;
    }
    return { ...this.current };
  }
}

const _expressionLerp = new ExpressionLerp(0.08);

/**
 * Convert a 27D emotion vector to full VRM blendshape weights.
 *
 * This is the main entry point for the avatar rendering loop.
 * Call once per frame, passing deltaTime in seconds.
 *
 * @param vector   - The 27D emotion vector from the WebSocket stream.
 * @param dt       - Frame delta time in seconds.
 * @param prevBlink - Previous blink weight (for blink state tracking).
 * @returns Complete VRM blendshape weights ready to apply to the model.
 */
export function emotionToBlendshapes(
  vector: EmotionVector27D,
  dt: number = 0.016,
): VrmBlendshapeWeights {
  // 1. Compute raw expression weights from emotion dimensions
  const raw: Record<string, number> = {};

  for (const [expr, contribs] of Object.entries(WEIGHTS)) {
    let sum = 0;
    let totalW = 0;
    for (const [dim, w] of Object.entries(contribs)) {
      const val = (vector as any)[dim] ?? 0;
      sum += val * w;
      totalW += Math.abs(w);
    }
    raw[expr] = totalW > 0 ? Math.min(1.0, sum / totalW) : 0.0;
  }

  // 2. Arousal-based intensity modulation
  const arousal = computeArousal(vector);
  const intensityBoost = 0.8 + arousal * 0.4;  // 0.8–1.2

  const modulated: Record<string, number> = {};
  for (const [k, v] of Object.entries(raw)) {
    modulated[k] = Math.min(1.0, v * intensityBoost);
  }

  // 3. Smooth via lerp
  _expressionLerp.factor = Math.min(1.0, dt * 5.0);
  _expressionLerp.setTarget(modulated);
  const smoothed = _expressionLerp.tick();

  // 4. Blink (procedural, emotion-modulated)
  const blinkWeight = updateBlink(dt, arousal);

  // 5. Gaze
  const gaze = computeGaze(vector);

  // 6. Neutral = inverse of strongest active expression
  const maxExpr = Math.max(
    smoothed.happy ?? 0, smoothed.angry ?? 0, smoothed.sad ?? 0,
    smoothed.relaxed ?? 0, smoothed.surprised ?? 0,
  );
  const neutral = Math.max(0, 1.0 - maxExpr * 0.8);

  return {
    happy: smoothed.happy ?? 0,
    angry: smoothed.angry ?? 0,
    sad: smoothed.sad ?? 0,
    relaxed: smoothed.relaxed ?? 0,
    surprised: smoothed.surprised ?? 0,
    aa: smoothed.aa ?? 0,
    ih: smoothed.ih ?? 0,
    ou: smoothed.ou ?? 0,
    ee: smoothed.ee ?? 0,
    oh: smoothed.oh ?? 0,
    blink: blinkWeight,
    blinkLeft: blinkWeight,
    blinkRight: blinkWeight,
    lookUp: gaze.lookUp,
    lookDown: gaze.lookDown,
    lookLeft: gaze.lookLeft,
    lookRight: gaze.lookRight,
    neutral,
  };
}

/**
 * Compute arousal (activation level) from the 27D vector.
 */
export function computeArousal(vector: EmotionVector27D): number {
  const highArousalDims = [
    vector.joy, vector.anger, vector.surprise, vector.fear,
    vector.awe, vector.wonder, vector.fascination, vector.curiosity,
  ];
  return highArousalDims.reduce((a, b) => a + b, 0) / highArousalDims.length;
}

/**
 * Compute valence (-1 to +1) from the 27D vector.
 */
export function computeValence(vector: EmotionVector27D): number {
  const pos = vector.joy + vector.love + vector.trust + vector.interest +
    vector.serenity + vector.gratitude + vector.beauty + vector.compassion;
  const neg = vector.fear + vector.sadness + vector.anger + vector.disgust +
    vector.shame + vector.envy + vector.boredom + vector.melancholy;
  return (pos - neg) / 8;
}
