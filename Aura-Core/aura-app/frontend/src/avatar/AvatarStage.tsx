"use client";

/**
 * AvatarStage — the cognitive-layer avatar rendered with Three.js.
 *
 * Renders a placeholder head (code-built, ARKit-named morph targets) driven
 * by the avatar controller each frame. Falls back to the spiral on any error.
 * Only renders when NEXT_PUBLIC_AVATAR_STAGE=1.
 */

import React, { useRef, useEffect, useState, useCallback } from 'react';
import * as THREE from 'three';
import SpiralAvatar from '@/components/SpiralAvatar';
import { PlaceholderHead } from './placeholderHead';
import { AvatarController, CognitiveLayer } from '@/avatar/controller/index';

interface AvatarStageProps {
  size?: number;
  className?: string;
  cognitiveState?: string;
}

/** Check whether the avatar stage feature flag is enabled. */
function isAvatarStageEnabled(): boolean {
  if (typeof process === "undefined" || typeof process.env === "undefined") {
    return false;
  }
  return process.env.NEXT_PUBLIC_AVATAR_STAGE === "1";
}

/** Pixel ratio cap: 1.5 on narrow screens, 2.0 otherwise. */
function getPixelRatioCap(): number {
  if (typeof window === "undefined") return 1.5;
  return window.innerWidth < 640 ? 1.5 : 2.0;
}

export default function AvatarStage({ size = 200, className = "", cognitiveState = "attending" }: AvatarStageProps) {
  // Render only when the feature flag is enabled
  if (!isAvatarStageEnabled()) {
    return null;
  }

  const [error, setError] = useState<Error | null>(null);
  const mountRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<AvatarController | null>(null);
  const headRef = useRef<PlaceholderHead | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const lastTimeRef = useRef<number>(0);
  const frameRef = useRef<number | null>(null);
  const cognitiveStateRef = useRef(cognitiveState);

  // Keep cognitiveState ref in sync
  cognitiveStateRef.current = cognitiveState;

  // Build the scene on mount
  const setupScene = useCallback(() => {
    if (!mountRef.current) return;

    try {
      const mount = mountRef.current;

      // Scene
      const scene = new THREE.Scene();
      sceneRef.current = scene;

      // Perspective camera with portrait framing (taller than wide)
      const aspect = size / (size * 1.3);
      const camera = new THREE.PerspectiveCamera(45, aspect, 0.1, 100);
      camera.position.set(0, 0, 2.2);
      camera.lookAt(0, 0, 0);
      cameraRef.current = camera;

      // Renderer
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(size, size * 1.3);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, getPixelRatioCap()));
      renderer.shadowMap.enabled = true;
      mount.appendChild(renderer.domElement);
      rendererRef.current = renderer;

      // Lights
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
      scene.add(ambientLight);

      const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
      directionalLight.position.set(1, 1, 1);
      directionalLight.castShadow = true;
      scene.add(directionalLight);

      // Placeholder head with ARKit morph targets
      const head = new PlaceholderHead();
      head.getMesh().position.set(0, 0, 0);
      scene.add(head.getMesh());
      headRef.current = head;

      // Avatar controller with cognitive layer (layer 3)
      const controller = new AvatarController({ noiseSeed: 42 });
      const cognitiveLayer = new CognitiveLayer();
      controller.registerLayer(cognitiveLayer);
      controllerRef.current = controller;

      lastTimeRef.current = performance.now();

      // Animation loop
      const animate = (time: number) => {
        if (!rendererRef.current || !sceneRef.current || !cameraRef.current ||
            !headRef.current || !controllerRef.current) {
          frameRef.current = requestAnimationFrame(animate);
          return;
        }

        const now = time;
        const dt = (now - lastTimeRef.current) / 1000;
        lastTimeRef.current = now;

        // Drive the controller each frame with the current cognitive state
        const mixResult = controller.update(dt, {
          t: now / 1000,
          dt,
          cognitiveState: cognitiveStateRef.current,
          emotionDeviation: {},
          isSpeaking: false,
          visemes: {},
          gazeTarget: null,
          eventPulses: [],
          gestureClip: null,
          config: undefined as any,
        });

        // Apply brow modifiers from cognitive output to morph targets
        const headInstance = headRef.current;
        const browChannels = ["browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight"];
        for (const ch of browChannels) {
          const val = mixResult.channels[ch as any];
          if (val !== undefined && val > 0) {
            headInstance.setShape(ch, val);
          }
        }

        // Apply head tilt
        const headTilt = mixResult.channels["head"];
        if (headTilt !== undefined) {
          head.getMesh().rotation.z = headTilt;
        }

        // Apply gaze via eye bone rotations
        const eyeL = mixResult.channels["eyeL"] ?? 0;
        const eyeR = mixResult.channels["eyeR"] ?? 0;
        const gazeYaw = (eyeL + eyeR) * 0.5;
        const gazePitch = (eyeL - eyeR) * 0.5;
        head.getMesh().rotation.y = gazeYaw;
        head.getMesh().rotation.x = gazePitch;

        rendererRef.current.render(sceneRef.current, cameraRef.current);
        frameRef.current = requestAnimationFrame(animate);
      };

      frameRef.current = requestAnimationFrame(animate);

      // Handle window resize
      const handleResize = () => {
        if (!mountRef.current || !rendererRef.current || !cameraRef.current) return;
        const width = size;
        const height = size * 1.3;
        rendererRef.current.setSize(width, height);
        rendererRef.current.setPixelRatio(Math.min(window.devicePixelRatio, getPixelRatioCap()));
        cameraRef.current.aspect = width / height;
        cameraRef.current.updateProjectionMatrix();
      };

      window.addEventListener('resize', handleResize);

      // Cleanup
      return () => {
        if (frameRef.current) {
          cancelAnimationFrame(frameRef.current);
        }
        window.removeEventListener('resize', handleResize);
        if (mount && rendererRef.current) {
          mount.removeChild(rendererRef.current.domElement);
          rendererRef.current.dispose();
        }
        sceneRef.current = null;
        cameraRef.current = null;
        rendererRef.current = null;
        headRef.current = null;
        controllerRef.current = null;
      };
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, [size]);

  useEffect(() => {
    const cleanup = setupScene();
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size]);

  // If error, render the spiral fallback
  if (error) {
    console.error("AvatarStage error, falling back to spiral:", error);
    return <SpiralAvatar size={size} className={className} />;
  }

  return (
    <div
      ref={mountRef}
      className={`avatar-stage ${className}`}
      style={{
        width: size,
        height: size * 1.3,
        borderRadius: '12px',
        overflow: 'hidden',
        background: '#0f0f14',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    />
  );
}
