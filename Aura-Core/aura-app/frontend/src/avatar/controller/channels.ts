/**
 * Channel definitions for the avatar controller.
 * Contains the 52 ARKit blend shape names plus bone channels,
 * each assigned to a group for ownership resolution.
 */

export type ChannelGroup =
  | "upperFace"
  | "lowerFace"
  | "eyes"
  | "jaw"
  | "head"
  | "body"
  | "arms";

/** The 52 standard ARKit blend shape names. */
export const ARKIT_BLEND_SHAPES: readonly string[] = [
  // Brow (5)
  "browDownLeft",
  "browDownRight",
  "browInnerUp",
  "browOuterUpLeft",
  "browOuterUpRight",
  // Cheek (3)
  "cheekPuff",
  "cheekSquintLeft",
  "cheekSquintRight",
  // Eye (14)
  "eyeBlinkLeft",
  "eyeBlinkRight",
  "eyeLookDownLeft",
  "eyeLookDownRight",
  "eyeLookInLeft",
  "eyeLookInRight",
  "eyeLookOutLeft",
  "eyeLookOutRight",
  "eyeLookUpLeft",
  "eyeLookUpRight",
  "eyeSquintLeft",
  "eyeSquintRight",
  "eyeWideLeft",
  "eyeWideRight",
  // Jaw (4)
  "jawForward",
  "jawLeft",
  "jawOpen",
  "jawRight",
  // Mouth (21)
  "mouthClose",
  "mouthDimpleLeft",
  "mouthDimpleRight",
  "mouthFunnel",
  "mouthLeft",
  "mouthLowerDownLeft",
  "mouthLowerDownRight",
  "mouthPressLeft",
  "mouthPressRight",
  "mouthPucker",
  "mouthRight",
  "mouthRollLower",
  "mouthRollUpper",
  "mouthShrugLower",
  "mouthShrugUpper",
  "mouthSmileLeft",
  "mouthSmileRight",
  "mouthStretchLeft",
  "mouthStretchRight",
  "mouthUpperUpLeft",
  "mouthUpperUpRight",
  // Nose (2)
  "noseSneerLeft",
  "noseSneerRight",
  // Tongue (1)
  "tongueOut",
] as const;

/** Bone channels for body animation. */
export const BONE_CHANNELS: readonly string[] = [
  "spine",
  "chest",
  "neck",
  "head",
  "eyeL",
  "eyeR",
  "shoulderL",
  "shoulderR",
  "upperArmL",
  "upperArmR",
  "lowerArmL",
  "lowerArmR",
  "handL",
  "handR",
] as const;

/** All channel names: ARKit blend shapes + bone channels. */
export type Channel = (typeof ARKIT_BLEND_SHAPES)[number] | (typeof BONE_CHANNELS)[number];

export const ALL_CHANNELS: readonly Channel[] = [
  ...ARKIT_BLEND_SHAPES,
  ...BONE_CHANNELS,
] as const;

/** Map each channel to its ownership group. */
export const CHANNEL_GROUPS: Readonly<Record<Channel, ChannelGroup>> = {
  // Upper face: brows, forehead, upper eyelids
  browDownLeft: "upperFace",
  browDownRight: "upperFace",
  browInnerUp: "upperFace",
  browOuterUpLeft: "upperFace",
  browOuterUpRight: "upperFace",
  // Cheeks can affect both upper and lower, but primary is upper
  cheekPuff: "upperFace",
  cheekSquintLeft: "upperFace",
  cheekSquintRight: "upperFace",
  // Eyes: gaze, blinks, squints, wide
  eyeBlinkLeft: "eyes",
  eyeBlinkRight: "eyes",
  eyeLookDownLeft: "eyes",
  eyeLookDownRight: "eyes",
  eyeLookInLeft: "eyes",
  eyeLookInRight: "eyes",
  eyeLookOutLeft: "eyes",
  eyeLookOutRight: "eyes",
  eyeLookUpLeft: "eyes",
  eyeLookUpRight: "eyes",
  eyeSquintLeft: "eyes",
  eyeSquintRight: "eyes",
  eyeWideLeft: "eyes",
  eyeWideRight: "eyes",
  // Jaw
  jawForward: "jaw",
  jawLeft: "jaw",
  jawOpen: "jaw",
  jawRight: "jaw",
  // Lower face: mouth shapes
  mouthClose: "lowerFace",
  mouthDimpleLeft: "lowerFace",
  mouthDimpleRight: "lowerFace",
  mouthFunnel: "lowerFace",
  mouthLeft: "lowerFace",
  mouthLowerDownLeft: "lowerFace",
  mouthLowerDownRight: "lowerFace",
  mouthPressLeft: "lowerFace",
  mouthPressRight: "lowerFace",
  mouthPucker: "lowerFace",
  mouthRight: "lowerFace",
  mouthRollLower: "lowerFace",
  mouthRollUpper: "lowerFace",
  mouthShrugLower: "lowerFace",
  mouthShrugUpper: "lowerFace",
  mouthSmileLeft: "lowerFace",
  mouthSmileRight: "lowerFace",
  mouthStretchLeft: "lowerFace",
  mouthStretchRight: "lowerFace",
  mouthUpperUpLeft: "lowerFace",
  mouthUpperUpRight: "lowerFace",
  // Nose
  noseSneerLeft: "lowerFace",
  noseSneerRight: "lowerFace",
  // Tongue
  tongueOut: "lowerFace",
  // Bone channels
  spine: "body",
  chest: "body",
  neck: "body",
  head: "head",
  eyeL: "eyes",
  eyeR: "eyes",
  shoulderL: "arms",
  shoulderR: "arms",
  upperArmL: "arms",
  upperArmR: "arms",
  lowerArmL: "arms",
  lowerArmR: "arms",
  handL: "arms",
  handR: "arms",
};

/** Channels grouped by ownership group. */
export const CHANNELS_BY_GROUP: Readonly<Record<ChannelGroup, readonly Channel[]>> = {
  upperFace: ARKIT_BLEND_SHAPES.filter((c) => CHANNEL_GROUPS[c] === "upperFace"),
  lowerFace: ARKIT_BLEND_SHAPES.filter((c) => CHANNEL_GROUPS[c] === "lowerFace"),
  eyes: [...ARKIT_BLEND_SHAPES.filter((c) => CHANNEL_GROUPS[c] === "eyes"), "eyeL", "eyeR"],
  jaw: ARKIT_BLEND_SHAPES.filter((c) => CHANNEL_GROUPS[c] === "jaw"),
  head: ["head"],
  body: ["spine", "chest", "neck"],
  arms: ["shoulderL", "shoulderR", "upperArmL", "upperArmR", "lowerArmL", "lowerArmR", "handL", "handR"],
};

/** Check if a channel is a face shape (blend shape) vs a bone channel. */
export function isFaceShape(channel: Channel): boolean {
  return ARKIT_BLEND_SHAPES.includes(channel as (typeof ARKIT_BLEND_SHAPES)[number]);
}

/** Check if a channel is a bone channel. */
export function isBoneChannel(channel: Channel): boolean {
  return BONE_CHANNELS.includes(channel as (typeof BONE_CHANNELS)[number]);
}