/**
 * PlaceholderHead: a head built entirely in code (no downloaded asset, so no
 * licence entry is needed) with morph targets named after the ARKit blend
 * shapes the tables use. Simple displacements per shape.
 *
 * Rule 2: nothing in the controller depends on this module.
 */

import * as THREE from 'three';

/** The 52 ARKit blend shape names (mirrors channels.ts ARKIT_BLEND_SHAPES). */
const ARKIT_BLEND_SHAPES: readonly string[] = [
  "browDownLeft",
  "browDownRight",
  "browInnerUp",
  "browOuterUpLeft",
  "browOuterUpRight",
  "cheekPuff",
  "cheekSquintLeft",
  "cheekSquintRight",
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
  "jawForward",
  "jawLeft",
  "jawOpen",
  "jawRight",
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
  "noseSneerLeft",
  "noseSneerRight",
  "tongueOut",
] as const;

type ArkitShape = (typeof ARKIT_BLEND_SHAPES)[number];

/** Displacement magnitude for morph targets. */
const DISPLACE = 0.12;

/**
 * Builds a simple sphere-based head geometry with one morph target per ARKit
 * blend shape. Each morph target displaces vertices in a region appropriate to
 * the shape (brow, eye, mouth, jaw, cheek, nose, tongue).
 *
 * Returns a Three.js Mesh with morph targets ready for influence weights.
 */
export function buildPlaceholderHead(): THREE.Mesh {
  // Base geometry: a sphere scaled like a head (taller than wide)
  const geometry = new THREE.SphereGeometry(0.5, 32, 32);
  geometry.scale(0.9, 1.0, 0.8); // Head-like proportions

  const positionAttribute = geometry.attributes.position as THREE.BufferAttribute;
  const vertexCount = positionAttribute.count;
  const positions = positionAttribute.array as Float32Array;

  // Helper: read a vertex position
  const getVertex = (i: number) => ({
    x: positions[i * 3],
    y: positions[i * 3 + 1],
    z: positions[i * 3 + 2],
  });

  // Helper: classify a vertex into a facial region based on its position
  const regionOf = (pos: { x: number; y: number; z: number }): string => {
    const { x, y, z } = pos;
    const front = z > 0.25; // front-facing vertices
    const top = y > 0.2; // upper region (brow/forehead)
    const bottom = y < -0.2; // lower region (jaw/chin)
    const left = x < -0.1;
    const right = x > 0.1;
    const center = Math.abs(x) <= 0.1;

    if (top && front) {
      if (left) return "browLeft";
      if (right) return "browRight";
      return "browCenter";
    }
    if (bottom && front) {
      if (left) return "jawLeft";
      if (right) return "jawRight";
      return "jawCenter";
    }
    if (front && Math.abs(y) < 0.15) {
      if (left) return "mouthLeft";
      if (right) return "mouthRight";
      return "mouthCenter";
    }
    if (front && y > 0.0 && y < 0.2) {
      if (left) return "cheekLeft";
      if (right) return "cheekRight";
      return "cheekCenter";
    }
    if (Math.abs(z) > 0.7) return "back";
    return "other";
  };

  // Classify all vertices once
  const regions: string[] = [];
  for (let i = 0; i < vertexCount; i++) {
    regions.push(regionOf(getVertex(i)));
  }

  // Build a morph target for each ARKit shape
  const morphTargets: Float32Array[] = [];

  for (const shape of ARKIT_BLEND_SHAPES) {
    const target = new Float32Array(vertexCount * 3);

    for (let i = 0; i < vertexCount; i++) {
      const pos = getVertex(i);
      const region = regions[i];
      let dx = 0;
      let dy = 0;
      let dz = 0;

      // Simple per-shape displacements
      switch (shape) {
        // Brow shapes
        case "browInnerUp":
          if (region === "browCenter" || region === "browLeft" || region === "browRight") {
            dy = DISPLACE * 0.8;
          }
          break;
        case "browOuterUpLeft":
          if (region === "browLeft") {
            dy = DISPLACE;
            dx = -DISPLACE * 0.3;
          }
          break;
        case "browOuterUpRight":
          if (region === "browRight") {
            dy = DISPLACE;
            dx = DISPLACE * 0.3;
          }
          break;
        case "browDownLeft":
          if (region === "browLeft") {
            dy = -DISPLACE * 0.7;
          }
          break;
        case "browDownRight":
          if (region === "browRight") {
            dy = -DISPLACE * 0.7;
          }
          break;

        // Eye shapes
        case "eyeWideLeft":
        case "eyeWideRight":
          if (region === "cheekLeft" || region === "cheekRight" || region === "browLeft" || region === "browRight") {
            dy = DISPLACE * 0.5;
            dz = DISPLACE * 0.3;
          }
          break;
        case "eyeSquintLeft":
        case "eyeSquintRight":
          if (region === "cheekLeft" || region === "cheekRight") {
            dy = -DISPLACE * 0.4;
          }
          if (region === "browLeft" || region === "browRight") {
            dy = DISPLACE * 0.3;
          }
          break;
        case "eyeBlinkLeft":
        case "eyeBlinkRight":
          if (region === "cheekLeft" || region === "cheekRight") {
            dy = -DISPLACE * 0.6;
            dz = DISPLACE * 0.4;
          }
          break;
        case "eyeLookUpLeft":
        case "eyeLookUpRight":
          if (region === "browLeft" || region === "browRight" || region === "cheekLeft" || region === "cheekRight") {
            dy = DISPLACE * 0.4;
          }
          break;
        case "eyeLookDownLeft":
        case "eyeLookDownRight":
          if (region === "cheekLeft" || region === "cheekRight") {
            dy = -DISPLACE * 0.4;
          }
          break;
        case "eyeLookInLeft":
          if (region === "cheekLeft" || region === "browLeft") {
            dx = DISPLACE * 0.5;
          }
          break;
        case "eyeLookInRight":
          if (region === "cheekRight" || region === "browRight") {
            dx = -DISPLACE * 0.5;
          }
          break;
        case "eyeLookOutLeft":
          if (region === "cheekLeft" || region === "browLeft") {
            dx = -DISPLACE * 0.5;
          }
          break;
        case "eyeLookOutRight":
          if (region === "cheekRight" || region === "browRight") {
            dx = DISPLACE * 0.5;
          }
          break;

        // Jaw shapes
        case "jawOpen":
          if (region === "jawCenter" || region === "jawLeft" || region === "jawRight") {
            dy = -DISPLACE;
            dz = DISPLACE * 0.3;
          }
          break;
        case "jawForward":
          if (region === "jawCenter" || region === "jawLeft" || region === "jawRight") {
            dz = DISPLACE;
          }
          break;
        case "jawLeft":
          if (region === "jawLeft") {
            dx = -DISPLACE;
            dy = -DISPLACE * 0.3;
          }
          break;
        case "jawRight":
          if (region === "jawRight") {
            dx = DISPLACE;
            dy = -DISPLACE * 0.3;
          }
          break;

        // Mouth shapes
        case "mouthSmileLeft":
          if (region === "mouthLeft") {
            dx = -DISPLACE;
            dy = DISPLACE * 0.4;
          }
          break;
        case "mouthSmileRight":
          if (region === "mouthRight") {
            dx = DISPLACE;
            dy = DISPLACE * 0.4;
          }
          break;
        case "mouthFunnel":
          if (region === "mouthCenter") {
            dz = DISPLACE;
            dy = DISPLACE * 0.2;
          }
          break;
        case "mouthPucker":
          if (region === "mouthCenter") {
            dz = DISPLACE * 0.8;
          }
          break;
        case "mouthOpen":
          if (region === "mouthCenter") {
            dy = -DISPLACE * 0.5;
            dz = DISPLACE * 0.3;
          }
          break;
        case "mouthLowerDownLeft":
          if (region === "mouthLeft") {
            dy = -DISPLACE * 0.6;
          }
          break;
        case "mouthLowerDownRight":
          if (region === "mouthRight") {
            dy = -DISPLACE * 0.6;
          }
          break;
        case "mouthUpperUpLeft":
          if (region === "mouthLeft") {
            dy = DISPLACE * 0.5;
          }
          break;
        case "mouthUpperUpRight":
          if (region === "mouthRight") {
            dy = DISPLACE * 0.5;
          }
          break;
        case "mouthPressLeft":
        case "mouthPressRight":
          if (region === "mouthLeft" || region === "mouthRight") {
            dz = DISPLACE * 0.3;
          }
          break;
        case "mouthDimpleLeft":
          if (region === "mouthLeft") {
            dy = -DISPLACE * 0.4;
            dz = DISPLACE * 0.2;
          }
          break;
        case "mouthDimpleRight":
          if (region === "mouthRight") {
            dy = -DISPLACE * 0.4;
            dz = DISPLACE * 0.2;
          }
          break;
        case "mouthStretchLeft":
          if (region === "mouthLeft") {
            dx = -DISPLACE * 0.8;
          }
          break;
        case "mouthStretchRight":
          if (region === "mouthRight") {
            dx = DISPLACE * 0.8;
          }
          break;
        case "mouthShrugLower":
          if (region === "mouthCenter" || region === "mouthLeft" || region === "mouthRight") {
            dy = -DISPLACE * 0.5;
          }
          break;
        case "mouthShrugUpper":
          if (region === "mouthCenter" || region === "mouthLeft" || region === "mouthRight") {
            dy = DISPLACE * 0.5;
          }
          break;
        case "mouthClose":
          if (region === "mouthCenter") {
            dy = DISPLACE * 0.2;
            dz = -DISPLACE * 0.2;
          }
          break;
        case "mouthLeft":
          if (region === "mouthLeft") {
            dx = -DISPLACE;
          }
          break;
        case "mouthRight":
          if (region === "mouthRight") {
            dx = DISPLACE;
          }
          break;

        // Cheek shapes
        case "cheekPuff":
          if (region === "cheekLeft" || region === "cheekRight" || region === "cheekCenter") {
            dz = DISPLACE;
          }
          break;
        case "cheekSquintLeft":
          if (region === "cheekLeft") {
            dy = DISPLACE * 0.4;
            dz = DISPLACE * 0.2;
          }
          break;
        case "cheekSquintRight":
          if (region === "cheekRight") {
            dy = DISPLACE * 0.4;
            dz = DISPLACE * 0.2;
          }
          break;

        // Nose shapes
        case "noseSneerLeft":
          if (region === "cheekLeft" || region === "mouthCenter") {
            dy = DISPLACE * 0.3;
            dz = DISPLACE * 0.2;
          }
          break;
        case "noseSneerRight":
          if (region === "cheekRight" || region === "mouthCenter") {
            dy = DISPLACE * 0.3;
            dz = DISPLACE * 0.2;
          }
          break;

        // Tongue
        case "tongueOut":
          if (region === "mouthCenter") {
            dz = DISPLACE * 0.6;
            dy = -DISPLACE * 0.2;
          }
          break;

        default:
          // No displacement for unknown shapes
          break;
      }

      target[i * 3] = pos.x + dx;
      target[i * 3 + 1] = pos.y + dy;
      target[i * 3 + 2] = pos.z + dz;
    }

    morphTargets.push(target);
  }

  // Set up morph attributes on the geometry
  geometry.morphAttributes.position = morphTargets.map((target) =>
    new THREE.BufferAttribute(target, 3)
  );
  geometry.morphTargetsRelative = false;

  const material = new THREE.MeshStandardMaterial({
    color: 0xeeeeee,
    roughness: 0.8,
    metalness: 0.1,
    flatShading: false,
  });

  const mesh = new THREE.Mesh(geometry, material);

  // Initialize all morph target influences to 0
  const influences: number[] = [];
  for (let i = 0; i < ARKIT_BLEND_SHAPES.length; i++) {
    influences.push(0);
  }
  mesh.morphTargetInfluences = influences;

  return mesh;
}

/**
 * PlaceholderHead wraps a Three.js mesh with ARKit-named morph targets and
 * provides a convenient API to set morph target influences by name.
 */
export class PlaceholderHead {
  readonly mesh: THREE.Mesh;
  private shapeToIndex: Map<string, number>;

  constructor() {
    this.mesh = buildPlaceholderHead();
    this.shapeToIndex = new Map();
    ARKIT_BLEND_SHAPES.forEach((shape, index) => {
      this.shapeToIndex.set(shape, index);
    });
  }

  /** Set the influence weight (0-1) for a named ARKit morph target. */
  setShape(shape: string, weight: number): void {
    const index = this.shapeToIndex.get(shape);
    if (index === undefined) return;
    const influences = this.mesh.morphTargetInfluences as number[];
    influences[index] = Math.max(0, Math.min(1, weight));
    this.mesh.morphTargetInfluences = influences;
  }

  /** Get the current influence weight for a named ARKit morph target. */
  getShape(shape: string): number {
    const index = this.shapeToIndex.get(shape);
    if (index === undefined) return 0;
    const influences = this.mesh.morphTargetInfluences as number[];
    return influences[index] ?? 0;
  }

  /** Set multiple shape weights at once. */
  setShapes(weights: Record<string, number>): void {
    for (const [shape, weight] of Object.entries(weights)) {
      this.setShape(shape, weight);
    }
  }

  /** Get the underlying Three.js mesh. */
  getMesh(): THREE.Mesh {
    return this.mesh;
  }
}
