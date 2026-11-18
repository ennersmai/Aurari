/**
 * Avatar Audio Bridge
 *
 * Lightweight event bus that decouples TTS audio generation (chat.tsx)
 * from VRM lip-sync consumption (AuraAvatar / VrmRenderer).
 *
 * Dispatches { buffer: ArrayBuffer, expression?: string } so the
 * avatar renderer can drive lip-sync without remounting.
 */

export interface AvatarAudioPayload {
  /** Raw audio buffer (WAV/MP3/etc.) ready for decode. */
  buffer: ArrayBuffer;
  /** Optional VRM expression preset name (e.g. "happy", "sad"). */
  expression?: string;
}

export type AvatarAudioHandler = (payload: AvatarAudioPayload) => void;

class AvatarAudioBridge {
  private handlers = new Set<AvatarAudioHandler>();

  /** Register a listener. Returns an unsubscribe function. */
  subscribe(handler: AvatarAudioHandler): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  /** Dispatch an audio payload to all registered listeners. */
  dispatch(payload: AvatarAudioPayload): void {
    for (const handler of this.handlers) {
      try {
        handler(payload);
      } catch (e) {
        console.error("[AvatarAudioBridge] handler error:", e);
      }
    }
  }
}

/** Singleton bridge instance. */
export const avatarAudioBridge = new AvatarAudioBridge();
