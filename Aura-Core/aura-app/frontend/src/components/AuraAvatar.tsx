"use client";

import { memo, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Box } from "@mui/material";
import { auraApi } from "@/services/auraApiService";
import { avatarAudioBridge } from "@/services/avatarAudioBridge";
import type { EmotionState, WebSocketEvent } from "@/types/aura";
import VrmRenderer from "./vrm-engine/VrmRenderer";
import VrmModelSelector from "./VrmModelSelector";
import { VrmStoreProvider } from "./vrm-engine/features/vrmStore/vrmStoreContext";
import { ViewerContext } from "./vrm-engine/features/vrmViewer/viewerContext";
import {
  emotionToVrmExpressions,
  type EmotionVector,
} from "./vrm-engine/features/vrmViewer/emotionToVrm";
import { AnimationRouter } from "./vrm-engine/features/vrmViewer/animationRouter";

// ---- 27D Emotion → VRM Blendshape Mapper --------------------------------

/**
 * The EmotionVector interface from emotionToVrm.ts uses the same 27 dimension
 * names as EmotionState from aura.ts. Cast and pass through directly.
 */
const toEmotionVector = (state: EmotionState): EmotionVector => ({
  love: state.love,
  joy: state.joy,
  interest: state.interest,
  trust: state.trust,
  fear: state.fear,
  sadness: state.sadness,
  anger: state.anger,
  surprise: state.surprise,
  disgust: state.disgust,
  awe: state.awe,
  beauty: state.beauty,
  wonder: state.wonder,
  serenity: state.serenity,
  melancholy: state.melancholy,
  nostalgia: state.nostalgia,
  empathy: state.empathy,
  gratitude: state.gratitude,
  pride: state.pride,
  shame: state.shame,
  envy: state.envy,
  compassion: state.compassion,
  curiosity: state.curiosity,
  confusion: state.confusion,
  certainty: state.certainty,
  doubt: state.doubt,
  fascination: state.fascination,
  boredom: state.boredom,
});

// ---- Animation Router (singleton, cooldowns persist across remounts) -----

const animationRouter = new AnimationRouter();

/** Minimum interval between animation route evaluations (ms). */
const ANIMATION_ROUTE_INTERVAL_MS = 3000;

function AuraAvatar() {
  const { viewer } = useContext(ViewerContext);

  /** The full 27D emotion state (used for blendshape summation). */
  const [emotionState, setEmotionState] = useState<EmotionState | null>(null);

  /** Stable ref for the latest emotion — used by the audio bridge callback. */
  const emotionRef = useRef<EmotionState | null>(null);

  /** Timestamp of last animation route evaluation. */
  const lastRouteRef = useRef(0);

  // ---- 27D Blendshape Application -----------------------------------------
  // Whenever emotionState changes, compute VRM expression weights from the
  // full 27D vector (not just the dominant emotion) and push to the model.

  useEffect(() => {
    if (!emotionState || !viewer.model) return;

    const vector = toEmotionVector(emotionState);
    const weights = emotionToVrmExpressions(vector);

    // ---- Biological subsystems --------------------------------------------
    // Push full 27D emotion to breath, gaze, saccades, and blendshapes.
    if (viewer.model.emoteController) {
      viewer.model.emoteController.setEmotionState(emotionState);
      viewer.model.emoteController.applyExpressionWeights(weights);
    } else {
      // Fallback: model loaded before EmoteController update.
      viewer.model.playEmotion(emotionState.dominant);
    }
  }, [emotionState, viewer.model]);

  // ---- Animation Reflex Layer ---------------------------------------------
  // Periodically evaluate the 27D vector against animation rules.
  // Only triggers when thresholds are crossed (magnitude-gated).

  useEffect(() => {
    // Wait until the VRM model is fully loaded before routing animations.
    if (!emotionState || !viewer.model?.vrm) return;

    const now = Date.now();
    if (now - lastRouteRef.current < ANIMATION_ROUTE_INTERVAL_MS) return;
    lastRouteRef.current = now;

    let cancelled = false;

    animationRouter.route(emotionState).then(({ animation, rule, file }) => {
      if (cancelled || !animation || !viewer.model?.vrm) return;

      console.log(`[AnimationRouter] Triggered: ${rule} (${file})`);

      const fileName = file.split("/").pop() ?? "idle_loop.vrma";

      viewer.model!.playAnimation(animation, fileName).catch((e) => {
        console.error("[AnimationRouter] playAnimation error:", e);
      });
    });

    return () => { cancelled = true; };
  }, [emotionState, viewer.model]);

  // ---- Stable callback for the audio bridge -------------------------------
  // The bridge callback needs the latest emotion, but we don't want it to
  // be a dependency of the subscribe effect (would re-subscribe on every
  // emotion change). Using a ref avoids that.

  const updateEmotion = useCallback((state: EmotionState) => {
    emotionRef.current = state;
    setEmotionState(state);
  }, []);

  // ---- WebSocket: emotion stream + audio ----------------------------------
  useEffect(() => {
    let reconnectTimeout: ReturnType<typeof setTimeout> | undefined;
    let heartbeatInterval: ReturnType<typeof setInterval> | undefined;
    let socket: WebSocket | undefined;

    const connect = () => {
      socket = auraApi.createEmotionWebSocket();
      socket.binaryType = "arraybuffer";

      socket.onopen = () => {
        console.log("✅ WebSocket connected to emotion stream");
        heartbeatInterval = setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ command: "heartbeat" }));
          }
        }, 25000);
      };

      socket.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          // Forward raw audio from the emotion WebSocket to the avatar bridge.
          avatarAudioBridge.dispatch({
            buffer: event.data,
            expression: emotionRef.current?.dominant ?? "neutral",
          });
          return;
        }

        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then((buf) => {
            avatarAudioBridge.dispatch({
              buffer: buf,
              expression: emotionRef.current?.dominant ?? "neutral",
            });
          });
          return;
        }

        const message = JSON.parse(event.data) as WebSocketEvent;

        if (message.type === "emotion_update") {
          updateEmotion(message.data);
        }
      };

      socket.onclose = () => {
        console.log("🔌 WebSocket disconnected, reconnecting in 5s...");
        if (heartbeatInterval) {
          clearInterval(heartbeatInterval);
        }

        reconnectTimeout = setTimeout(connect, 5000);
      };
    };

    connect();

    return () => {
      if (heartbeatInterval) {
        clearInterval(heartbeatInterval);
      }

      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }

      socket?.close();
    };
  }, [updateEmotion]);

  // ---- Avatar audio bridge → VRM lip-sync ---------------------------------
  useEffect(() => {
    const unsubscribe = avatarAudioBridge.subscribe(({ buffer, expression }) => {
      if (!viewer.model) {
        console.warn("[AuraAvatar] viewer.model not ready – skipping lip-sync");
        return;
      }

      viewer.model.speakSilent(buffer, {
        expression: expression ?? emotionRef.current?.dominant ?? "neutral",
      }).catch((e) => {
        console.error("[AuraAvatar] speakSilent error:", e);
      });
    });

    return unsubscribe;
  }, [viewer]);

  return (
    <VrmStoreProvider>
      <Box sx={{ position: "relative", width: "100%", height: "100%" }}>
        <VrmRenderer chatMode={false} />
        {/* Model selector overlay — top-right corner */}
        <Box
          sx={{
            position: "absolute",
            top: 8,
            right: 8,
            zIndex: 10,
          }}
        >
          <VrmModelSelector />
        </Box>
      </Box>
    </VrmStoreProvider>
  );
}

export default memo(AuraAvatar);
