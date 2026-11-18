'use client';

/**
 * AvatarCanvas — 3D VRM Avatar with Real-Time Emotion-Driven Animation
 *
 * Renders a VRM 1.0 avatar in a Three.js scene and continuously applies
 * blendshape weights computed from the 27D emotion vector streamed over
 * WebSocket from the FastAPI backend.
 *
 * Features:
 *   - Three.js + @pixiv/three-vrm rendering
 *   - WebSocket listener at ws://127.0.0.1:8080/v1/stream/emotions
 *   - 27D emotion → VRM blendshape translation via emotionToBlendshapes()
 *   - Procedural blinking, eye gaze, and expression morphing
 *   - Responsive canvas sizing
 *   - Graceful degradation: shows a fallback placeholder when VRM fails to load
 *
 * Usage:
 *   <AvatarCanvas vrmPath="/avatar.vrm" wsUrl="ws://127.0.0.1:8080/v1/stream/emotions" />
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import type { VRM } from '@pixiv/three-vrm';

import {
  emotionToBlendshapes,
  computeArousal,
  computeValence,
} from '@/utils/emotionToBlendshape';
import type {
  EmotionVector27D,
  EmotionStreamMessage,
  VrmBlendshapeWeights,
} from '@/utils/emotionToBlendshape';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AvatarCanvasProps {
  /** Path to the .vrm file (default: /avatar.vrm). */
  vrmPath?: string;
  /** WebSocket URL for emotion stream. */
  wsUrl?: string;
  /** Canvas width (default: 100% via CSS). */
  width?: number;
  /** Canvas height (default: 600). */
  height?: number;
}

// ---------------------------------------------------------------------------
// Camera defaults
// ---------------------------------------------------------------------------

const CAMERA_POSITION = new THREE.Vector3(0, 1.2, 2.5);
const CAMERA_LOOK_AT = new THREE.Vector3(0, 0.9, 0);

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const AvatarCanvas: React.FC<AvatarCanvasProps> = ({
  vrmPath = '/avatar.vrm',
  wsUrl = 'ws://127.0.0.1:8080/v1/stream/emotions',
  width,
  height = 600,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Three.js refs
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const vrmRef = useRef<VRM | null>(null);
  const animationFrameRef = useRef<number>(0);
  const clockRef = useRef<THREE.Clock>(new THREE.Clock());
  const wsRef = useRef<WebSocket | null>(null);
  const emotionRef = useRef<EmotionVector27D | null>(null);

  // UI state
  const [status, setStatus] = useState<'loading' | 'connected' | 'disconnected' | 'error'>('loading');
  const [dominantEmotion, setDominantEmotion] = useState<string>('neutral');
  const [errorMsg, setErrorMsg] = useState<string>('');

  // ------------------------------------------------------------------
  // WebSocket connection
  // ------------------------------------------------------------------
  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setStatus('connected');
        setErrorMsg('');
        console.log('[AvatarCanvas] WebSocket connected');
      };

      ws.onmessage = (event: MessageEvent<string>) => {
        try {
          const msg: EmotionStreamMessage = JSON.parse(event.data);
          if (msg.type === 'emotion_vector' && msg.vector) {
            emotionRef.current = msg.vector;
            if (msg.dominant) {
              setDominantEmotion(msg.dominant);
            }
          }
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        setStatus('disconnected');
        console.log('[AvatarCanvas] WebSocket disconnected, retrying in 3s...');
        setTimeout(connectWebSocket, 3000);
      };

      ws.onerror = () => {
        setStatus('error');
        setErrorMsg('WebSocket connection error');
      };

      wsRef.current = ws;
    } catch (e) {
      setStatus('error');
      setErrorMsg(`Failed to connect: ${e}`);
      setTimeout(connectWebSocket, 5000);
    }
  }, [wsUrl]);

  // ------------------------------------------------------------------
  // Three.js + VRM initialization
  // ------------------------------------------------------------------
  useEffect(() => {
    let mounted = true;

    const initThree = async () => {
      const container = containerRef.current;
      if (!container || !mounted) return;

      // --- Renderer ---
      const renderer = new THREE.WebGLRenderer({
        canvas: canvasRef.current!,
        alpha: true,
        antialias: true,
      });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width ?? container.clientWidth, height);
      renderer.shadowMap.enabled = true;
      rendererRef.current = renderer;

      // --- Scene ---
      const scene = new THREE.Scene();
      scene.background = null;  // transparent
      sceneRef.current = scene;

      // --- Camera ---
      const aspect = (width ?? container.clientWidth) / height;
      const camera = new THREE.PerspectiveCamera(35, aspect, 0.1, 30);
      camera.position.copy(CAMERA_POSITION);
      camera.lookAt(CAMERA_LOOK_AT);
      cameraRef.current = camera;

      // --- Lighting ---
      // Ambient
      scene.add(new THREE.AmbientLight(0xffffff, 1.2));

      // Key light
      const keyLight = new THREE.DirectionalLight(0xfff5e6, 3.0);
      keyLight.position.set(1, 2.5, 2);
      keyLight.castShadow = true;
      keyLight.shadow.mapSize.set(1024, 1024);
      scene.add(keyLight);

      // Fill light
      const fillLight = new THREE.DirectionalLight(0xc8d6ff, 1.5);
      fillLight.position.set(-1.5, 1, 1);
      scene.add(fillLight);

      // Rim light
      const rimLight = new THREE.DirectionalLight(0xffffff, 1.8);
      rimLight.position.set(0, 1.5, -1.5);
      scene.add(rimLight);

      // --- Ground plane (subtle shadow catcher) ---
      const groundGeo = new THREE.PlaneGeometry(5, 5);
      const groundMat = new THREE.ShadowMaterial({ opacity: 0.15 });
      const ground = new THREE.Mesh(groundGeo, groundMat);
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = -0.8;
      ground.receiveShadow = true;
      scene.add(ground);

      // --- Load VRM ---
      try {
        const gltfLoader = new GLTFLoader();
        gltfLoader.register((parser) => new VRMLoaderPlugin(parser));

        const gltf = await new Promise<any>((resolve, reject) => {
          gltfLoader.load(
            vrmPath,
            resolve,
            undefined,  // progress
            (err: unknown) => reject(err instanceof Error ? err : new Error(String(err))),
          );
        });

        const vrm: VRM = gltf.userData.vrm;
        if (!vrm) {
          throw new Error('VRM model not found in loaded GLTF (missing VRMLoaderPlugin?)');
        }

        // Optimize the model
        VRMUtils.removeUnnecessaryVertices(gltf.scene);
        VRMUtils.removeUnnecessaryJoints(gltf.scene);

        if (!mounted) return;

        vrm.scene.position.set(0, -0.15, 0);
        vrm.scene.traverse((child: THREE.Object3D) => {
          if (child instanceof THREE.Mesh) {
            child.castShadow = true;
            child.receiveShadow = true;
          }
        });

        scene.add(vrm.scene);
        vrmRef.current = vrm;
        console.log('[AvatarCanvas] VRM loaded successfully');
      } catch (e) {
        console.warn('[AvatarCanvas] VRM load failed, using fallback:', e);
        // Fallback: simple sphere placeholder
        if (mounted) {
          const sphereGeo = new THREE.SphereGeometry(0.4, 32, 32);
          const sphereMat = new THREE.MeshStandardMaterial({
            color: 0x6c5ce7,
            roughness: 0.4,
            metalness: 0.2,
          });
          const sphere = new THREE.Mesh(sphereGeo, sphereMat);
          sphere.position.set(0, 0.8, 0);
          sphere.castShadow = true;
          scene.add(sphere);
        }
      }

      // --- Start render loop ---
      const clock = clockRef.current;
      clock.start();

      const animate = () => {
        if (!mounted) return;
        animationFrameRef.current = requestAnimationFrame(animate);

        const dt = Math.min(clock.getDelta(), 0.1);  // cap to prevent spiral

        // Apply emotion → blendshapes
        const vrm = vrmRef.current;
        const emotion = emotionRef.current;
        if (vrm && emotion) {
          const weights: VrmBlendshapeWeights = emotionToBlendshapes(emotion, dt);

          // Apply expression weights
          const expManager = vrm.expressionManager;
          if (expManager) {
            expManager.setValue('happy', weights.happy);
            expManager.setValue('angry', weights.angry);
            expManager.setValue('sad', weights.sad);
            expManager.setValue('relaxed', weights.relaxed);
            expManager.setValue('surprised', weights.surprised);
            expManager.setValue('aa', weights.aa);
            expManager.setValue('ih', weights.ih);
            expManager.setValue('ou', weights.ou);
            expManager.setValue('ee', weights.ee);
            expManager.setValue('oh', weights.oh);
            expManager.setValue('blink', weights.blink);
            expManager.setValue('blinkLeft', weights.blinkLeft);
            expManager.setValue('blinkRight', weights.blinkRight);
            expManager.setValue('lookUp', weights.lookUp);
            expManager.setValue('lookDown', weights.lookDown);
            expManager.setValue('lookLeft', weights.lookLeft);
            expManager.setValue('lookRight', weights.lookRight);
            expManager.setValue('neutral', weights.neutral);
          }

          // Update VRM (bone transforms, etc.)
          vrm.update(dt);
        }

        if (renderer && scene && camera) {
          renderer.render(scene, camera);
        }
      };

      animate();
    };

    initThree();
    connectWebSocket();

    // --- Resize handler ---
    const handleResize = () => {
      const container = containerRef.current;
      if (!container || !rendererRef.current || !cameraRef.current) return;
      const w = width ?? container.clientWidth;
      const h = height;
      rendererRef.current.setSize(w, h);
      cameraRef.current.aspect = w / h;
      cameraRef.current.updateProjectionMatrix();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      mounted = false;
      window.removeEventListener('resize', handleResize);
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (rendererRef.current) {
        rendererRef.current.dispose();
        rendererRef.current = null;
      }
      if (vrmRef.current?.scene) {
        sceneRef.current?.remove(vrmRef.current.scene);
      }
    };
  }, [vrmPath, wsUrl, width, height, connectWebSocket]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div
      ref={containerRef}
      style={{
        position: 'relative',
        width: width ?? '100%',
        height,
        borderRadius: 16,
        overflow: 'hidden',
        background: 'radial-gradient(ellipse at center, rgba(30,30,60,0.6) 0%, rgba(10,10,20,0.9) 100%)',
      }}
    >
      <canvas ref={canvasRef} style={{ display: 'block' }} />

      {/* Status overlay */}
      {status !== 'connected' && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(0,0,0,0.4)',
            color: '#ccc',
            fontFamily: 'monospace',
            fontSize: 14,
            gap: 8,
          }}
        >
          {status === 'loading' && (
            <>
              <div className="animate-spin" style={{ fontSize: 32 }}>⟳</div>
              <span>Loading avatar...</span>
            </>
          )}
          {status === 'disconnected' && (
            <>
              <span>⚡ Emotion stream disconnected</span>
              <span style={{ fontSize: 11, color: '#888' }}>Retrying...</span>
            </>
          )}
          {status === 'error' && (
            <>
              <span style={{ color: '#f88' }}>⚠ Error</span>
              <span style={{ fontSize: 11, color: '#888' }}>{errorMsg}</span>
            </>
          )}
        </div>
      )}

      {/* Dominant emotion label */}
      {status === 'connected' && (
        <div
          style={{
            position: 'absolute',
            bottom: 12,
            left: 16,
            padding: '4px 12px',
            borderRadius: 8,
            background: 'rgba(0,0,0,0.5)',
            color: '#fff',
            fontSize: 12,
            fontFamily: 'monospace',
            textTransform: 'capitalize',
            pointerEvents: 'none',
          }}
        >
          {dominantEmotion}
        </div>
      )}
    </div>
  );
};

export default AvatarCanvas;
export type { AvatarCanvasProps };
