/**
 * Shared AnimationRouter instance.
 *
 * This singleton is used by both AuraAvatar (for reflex-based animation
 * routing) and chat.tsx (for L5-based animation overrides).
 *
 * By sharing the same instance, L5 overrides set in chat.tsx are
 * immediately visible to the animation routing loop in AuraAvatar.
 */

import { AnimationRouter } from "@/components/vrm-engine/features/vrmViewer/animationRouter";

export const animationRouter = new AnimationRouter();