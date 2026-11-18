declare module "@mkkellogg/gaussian-splats-3d";
declare module "@supabase/supabase-js";
declare module "three/src/renderers/webgpu/WebGPURenderer.js";

declare module "lil-gui" {
  export default class GUI {
    domElement: HTMLElement;
    controllers: { updateDisplay: () => void }[];
    constructor(options?: unknown);
    add(...args: unknown[]): { name: (value: string) => { onChange: (handler: (value: any) => void) => unknown }; onChange: (handler: (value: any) => void) => unknown };
    addFolder(...args: unknown[]): GUI;
    destroy(): void;
    close(): void;
  }
}

declare module "stats.js" {
  export default class Stats {
    dom: HTMLElement;
    constructor();
    begin(): void;
    end(): void;
    update(): void;
    showPanel(id: number): void;
    addPanel(panel: unknown): unknown;
    static Panel: new (name: string, fg: string, bg: string) => unknown;
  }
}

declare module "three-mesh-bvh" {
  export const computeBoundsTree: (...args: unknown[]) => unknown;
  export const disposeBoundsTree: (...args: unknown[]) => unknown;
  export const computeBatchedBoundsTree: (...args: unknown[]) => unknown;
  export const disposeBatchedBoundsTree: (...args: unknown[]) => unknown;
  export const acceleratedRaycast: (...args: unknown[]) => unknown;
  export class MeshBVHHelper extends import("three").Object3D {
    color: import("three").Color;
    constructor(mesh: unknown, depth?: number);
    update(): void;
  }
  export class StaticGeometryGenerator {
    constructor(object: unknown);
    generate(geometry?: unknown, options?: unknown): { refit: () => void };
  }
}

declare module "three/examples/jsm/controls/OrbitControls" {
  export class OrbitControls {
    target: import("three").Vector3;
    enabled: boolean;
    screenSpacePanning: boolean;
    minDistance: number;
    maxDistance: number;
    constructor(object: import("three").Camera, domElement?: HTMLElement);
    update(): void;
    dispose(): void;
  }
}

declare module "three/examples/jsm/loaders/GLTFLoader" {
  export type GLTF = any;
  export type GLTFParser = any;
  export interface GLTFLoaderPlugin { readonly parser: GLTFParser; name: string; afterRoot?(gltf: GLTF): Promise<void> | void }
  export class GLTFLoader {
    register(callback: (parser: GLTFParser) => GLTFLoaderPlugin): this;
    load(url: string, onLoad: (gltf: GLTF) => void, onProgress?: (event: ProgressEvent) => void, onError?: (error: unknown) => void): void;
    loadAsync(url: string): Promise<GLTF>;
    setDRACOLoader(loader: unknown): void;
  }
}

declare module "three/examples/jsm/loaders/DRACOLoader" {
  export class DRACOLoader {
    setDecoderPath(path: string): this;
    dispose(): void;
  }
}

declare module "three/examples/jsm/loaders/FBXLoader" {
  export class FBXLoader {
    load(url: string, onLoad: (asset: any) => void, onProgress?: (event: ProgressEvent) => void, onError?: (error: unknown) => void): void;
    loadAsync(url: string): Promise<any>;
  }
}

type XRSessionMode = "inline" | "immersive-vr" | "immersive-ar";
type XRFrame = unknown;
type XRInputSourceEvent = Event;
type XRSession = EventTarget & { end?: () => Promise<void> };
declare const XRRigidTransform: { new (position?: DOMPointInit, orientation?: DOMPointInit): unknown };


