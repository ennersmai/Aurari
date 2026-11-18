export const thumbPrefix = (url: string): string => url.replace(/\.[^/.]+$/, "");
export const ChatContext = null;
export const ViewerContext = null;
export const config: Record<string, string> = {};
export const updateConfig = () => {};
// emotionNames moved to ExpressionController.KNOWN_PRESETS (static Set).
// This avoids a mutable global array that was being pushed to from a side-effect.
export interface Screenplay { expression: string }
export interface Message { role?: string; content: string }
export interface Talk { message: string; expression: string }
export const hashCode = (text: string): string => {
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash << 5) - hash + text.charCodeAt(i);
    hash |= 0;
  }
  return hash.toString();
};
export const expandPrompt = async (prompt: string, values: Record<string, string>): Promise<string> => {
  return Object.entries(values).reduce((current, [key, value]) => current.replace(`[{${key}}]`, value), prompt);
};
export class WorkerBase {
  async generate(..._args: unknown[]) {
    return undefined;
  }
}
export type Table<T> = {
  put: (item: T) => unknown;
  toArray: () => Promise<T[]>;
  where: (key?: string) => { equals: (value?: unknown) => { modify: (item: Partial<T>) => unknown; first: () => Promise<T | undefined> } };
};
export class VrmDexieMock<T> {
  vrms: Table<T>;
  constructor() {
    const rows: T[] = [];
    this.vrms = {
      put: (item: T) => rows.push(item),
      toArray: async () => rows,
      where: () => ({
        equals: () => ({
          modify: () => undefined,
          first: async () => rows[0],
        }),
      }),
    };
  }
  close() {}
  version() {
    return { stores: () => undefined };
  }
}
export type GLTFSchema = any;




export namespace GLTFSchema {
  export interface IGLTF {
    extensionsUsed?: string[];
    extensions?: Record<string, unknown>;
    nodes?: any[];
    animations?: any[];
  }
  export interface IAnimation { channels: any[]; samplers?: any[] }
}
export const textsToScreenplay = (texts: string[]): Screenplay[] => texts.map((expression) => ({ expression }));

