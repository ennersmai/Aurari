/**
 * 27D Emotion Vector → VRM Expression Mapper
 *
 * Maps Aura's 27-dimensional emotional state to standard VRM expression
 * presets using linear interpolation for smooth facial transitions.
 *
 * VRM standard expressions: happy, angry, sad, relaxed, surprised,
 * aa, ih, ou, ee, oh, blink, blinkLeft, blinkRight, lookUp, lookDown,
 * lookLeft, lookRight, neutral
 */

/** Weighted contribution of each 27D dimension to each VRM expression. */
const EMOTION_TO_VRM_WEIGHTS: Record<string, Record<string, number>> = {
  happy: {
    joy: 1.0, love: 0.4, gratitude: 0.3, serenity: 0.2, pride: 0.3,
    amusement: 0.0, interest: 0.2, trust: 0.1, certainty: 0.1,
  },
  angry: {
    anger: 1.0, disgust: 0.5, fear: 0.2, envy: 0.4, shame: 0.1,
  },
  sad: {
    sadness: 1.0, melancholy: 0.7, nostalgia: 0.4, loneliness: 0.0,
    fear: 0.3, shame: 0.2, boredom: 0.2,
  },
  relaxed: {
    serenity: 1.0, trust: 0.5, love: 0.3, gratitude: 0.3, beauty: 0.4,
    awe: 0.2,
  },
  surprised: {
    surprise: 1.0, awe: 0.7, wonder: 0.6, fascination: 0.4, curiosity: 0.3,
    fear: 0.3, confusion: 0.2,
  },
  // Viseme-like expressions mapped to emotional states
  aa: { surprise: 0.8, awe: 0.5, wonder: 0.4 },
  ih: { interest: 0.6, curiosity: 0.7, confusion: 0.3 },
  ou: { sadness: 0.4, melancholy: 0.6, boredom: 0.3 },
  ee: { joy: 0.7, amusement: 0.0, love: 0.3 },
  oh: { surprise: 0.5, awe: 0.6, wonder: 0.5 },
};

export interface EmotionVector {
  love: number; joy: number; interest: number; trust: number;
  fear: number; sadness: number; anger: number; surprise: number;
  disgust: number; awe: number; beauty: number; wonder: number;
  serenity: number; melancholy: number; nostalgia: number;
  empathy: number; gratitude: number; pride: number; shame: number;
  envy: number; compassion: number; curiosity: number; confusion: number;
  certainty: number; doubt: number; fascination: number; boredom: number;
}

export interface VrmExpressionWeights {
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
}

/** Smooth interpolation state for lerp transitions. */
class LerpState {
  current: Record<string, number> = {};
  target: Record<string, number> = {};
  factor: number;

  /** Lerp factor per tick (0.05 = 5% toward target per tick). */
  constructor(factor: number = 0.05) {
    this.factor = factor;
  }

  setTarget(weights: Record<string, number>): void {
    this.target = { ...weights };
    // Initialize current to target on first call.
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

/** Global lerp state shared across ticks. */
const lerpState = new LerpState(0.05);

/**
 * Convert a 27D emotion vector to VRM expression weights.
 * Returns smoothed values via lerp to avoid jittery facial transitions.
 */
export function emotionToVrmExpressions(
  vector: EmotionVector,
  deltaTime?: number
): VrmExpressionWeights {
  const raw: Record<string, number> = {};

  for (const [expr, weights] of Object.entries(EMOTION_TO_VRM_WEIGHTS)) {
    let sum = 0;
    let totalWeight = 0;
    for (const [dim, w] of Object.entries(weights)) {
      const val = (vector as any)[dim] ?? 0;
      sum += val * w;
      totalWeight += w;
    }
    raw[expr] = totalWeight > 0 ? Math.min(1, sum / totalWeight) : 0;
  }

  // Adjust lerp factor based on deltaTime for frame-rate independence.
  const factor = deltaTime ? Math.min(1, deltaTime * 3) : 0.05;
  lerpState.factor = factor;
  lerpState.setTarget(raw);
  const smoothed = lerpState.tick();

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
  };
}

/**
 * Compute an energy/arousal value from the 27D vector.
 * Used to modulate TTS temperature and animation speed.
 */
export function computeEmotionEnergy(vector: EmotionVector): number {
  const highArousal = [
    vector.joy, vector.anger, vector.surprise, vector.fear,
    vector.awe, vector.wonder, vector.fascination, vector.curiosity,
  ];
  const sum = highArousal.reduce((a, b) => a + b, 0);
  return Math.min(1, sum / highArousal.length);
}

/**
 * Compute valence from the 27D vector (-1 to +1).
 */
export function computeEmotionValence(vector: EmotionVector): number {
  const pos = vector.joy + vector.love + vector.trust + vector.interest +
    vector.serenity + vector.gratitude + vector.beauty + vector.compassion;
  const neg = vector.fear + vector.sadness + vector.anger + vector.disgust +
    vector.shame + vector.envy + vector.boredom + vector.melancholy;
  return (pos - neg) / 8;
}
