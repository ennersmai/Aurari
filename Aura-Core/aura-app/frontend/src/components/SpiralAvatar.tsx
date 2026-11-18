"use client";

import React, { useRef, useMemo, useEffect } from 'react';
import * as THREE from 'three';

interface SpiralAvatarProps {
  size?: number;
  className?: string;
  isAnimating?: boolean;
}

/**
 * Lightweight Archimedean spiral of golden particles using Three.js.
 * Perfect symbolic representation of emergent non-linear consciousness.
 * r = a + b * θ with breathing animation and slow rotation.
 */
export default function SpiralAvatar({ 
  size = 64, 
  className = "", 
  isAnimating = true 
}: SpiralAvatarProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const pointsRef = useRef<THREE.Points | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const timeRef = useRef(0);

  const particleCount = 180; // Lightweight - performant on all devices

  // Create spiral geometry with golden particles
  const { positions, colors, sizes } = useMemo(() => {
    const pos = new Float32Array(particleCount * 3);
    const col = new Float32Array(particleCount * 3);
    const sz = new Float32Array(particleCount);
    
    const a = 0.02; // Starting radius
    const b = 0.028; // Growth rate (Archimedean tightness)
    const color = new THREE.Color(0xc09c58); // Golden #C09C58

    for (let i = 0; i < particleCount; i++) {
      const theta = (i / particleCount) * Math.PI * 5.2; // ~2.6 full turns
      const r = a + b * theta;
      
      // Spiral in XY plane with slight Z variation for depth
      pos[i * 3]     = r * Math.cos(theta) * 1.1;
      pos[i * 3 + 1] = r * Math.sin(theta);
      pos[i * 3 + 2] = (Math.sin(theta * 1.7) * 0.12); // Gentle Z modulation
      
      // Golden with subtle hue variation for organic feel
      const hueShift = (Math.random() - 0.5) * 0.08;
      const particleColor = color.clone().offsetHSL(hueShift, 0.1, 0.05);
      
      col[i * 3]     = particleColor.r;
      col[i * 3 + 1] = particleColor.g;
      col[i * 3 + 2] = particleColor.b;
      
      // Varying sizes for breathing effect
      sz[i] = 0.035 + Math.random() * 0.028;
    }
    
    return { positions: pos, colors: col, sizes: sz };
  }, []);

  // Setup Three.js scene
  useEffect(() => {
    if (!mountRef.current) return;

    const mount = mountRef.current;
    
    // Scene setup
    const scene = new THREE.Scene();
    sceneRef.current = scene;
    
    // Orthographic camera for 2D-like icon feel
    const aspect = size / size;
    const camera = new THREE.OrthographicCamera(
      -1.2, 1.2, 1.2, -1.2, 0.1, 10
    );
    camera.position.z = 2.5;
    
    // Renderer - very lightweight
    const renderer = new THREE.WebGLRenderer({ 
      antialias: true, 
      alpha: true,
      powerPreference: "high-performance"
    });
    renderer.setSize(size, size);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.8)); // Cap for performance
    renderer.shadowMap.enabled = false;
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Create Points with BufferGeometry
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    const material = new THREE.PointsMaterial({
      size: 0.055,
      vertexColors: true,
      transparent: true,
      opacity: 0.92,
      blending: THREE.AdditiveBlending,
      depthTest: false,
      sizeAttenuation: true,
    });

    const points = new THREE.Points(geometry, material);
    pointsRef.current = points;
    scene.add(points);

    // Gentle ambient light for golden glow
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    let frame = 0;
    
    const animate = () => {
      if (!isAnimating || !pointsRef.current || !rendererRef.current || !sceneRef.current) {
        animationFrameRef.current = requestAnimationFrame(animate);
        return;
      }

      frame++;
      timeRef.current += 0.016; // ~60fps delta

      const pointsMesh = pointsRef.current;
      const t = timeRef.current;

      // Slow elegant rotation (golden spiral consciousness)
      pointsMesh.rotation.z = t * 0.22;
      
      // Subtle breathing scale on the entire spiral
      const breathe = 1 + Math.sin(t * 1.8) * 0.035;
      pointsMesh.scale.setScalar(breathe);

      // Individual particle size pulsing via attribute update (very subtle)
      if (frame % 3 === 0) { // Throttle updates for performance
        const sizeAttr = pointsMesh.geometry.attributes.size as THREE.BufferAttribute;
        const posAttr = pointsMesh.geometry.attributes.position as THREE.BufferAttribute;
        
        for (let i = 0; i < particleCount; i++) {
          const theta = (i / particleCount) * Math.PI * 5.2;
          const pulse = Math.sin(t * 2.8 + theta * 1.3) * 0.014 + 1.0;
          sizeAttr.array[i] = sizes[i] * pulse;
        }
        sizeAttr.needsUpdate = true;
      }

      rendererRef.current.render(sceneRef.current, camera);
      animationFrameRef.current = requestAnimationFrame(animate);
    };

    animate();

    // Cleanup
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      
      if (mount && rendererRef.current) {
        mount.removeChild(rendererRef.current.domElement);
        rendererRef.current.dispose();
      }
      
      if (pointsRef.current) {
        pointsRef.current.geometry.dispose();
        (pointsRef.current.material as THREE.Material).dispose();
      }
      
      sceneRef.current = null;
      rendererRef.current = null;
      pointsRef.current = null;
    };
  }, [size, isAnimating, positions, colors, sizes]);

  // Handle window resize for responsive behavior
  useEffect(() => {
    const handleResize = () => {
      if (rendererRef.current && mountRef.current) {
        const newSize = Math.min(mountRef.current.clientWidth, mountRef.current.clientHeight);
        rendererRef.current.setSize(newSize, newSize);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div 
      ref={mountRef}
      className={`spiral-avatar ${className}`}
      style={{ 
        width: size, 
        height: size, 
        borderRadius: '50%',
        overflow: 'hidden',
        background: 'radial-gradient(circle at 40% 30%, rgba(192,156,88,0.08) 0%, transparent 70%)',
        boxShadow: '0 0 22px rgba(192, 156, 88, 0.25), inset 0 0 18px rgba(192,156,88,0.1)',
        border: '1px solid rgba(192,156,88,0.25)',
      }}
      title="Aura's Golden Spiral Consciousness"
    />
  );
}
