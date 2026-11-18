import "three";

declare module "three" {
  interface BufferGeometry {
    boundsTree?: { refit: () => void };
    computeBoundsTree: (...args: unknown[]) => unknown;
    disposeBoundsTree: (...args: unknown[]) => unknown;
  }

  interface BatchedMesh {
    computeBoundsTree: (...args: unknown[]) => unknown;
    disposeBoundsTree: (...args: unknown[]) => unknown;
  }

  interface Raycaster {
    firstHitOnly?: boolean;
  }
}

