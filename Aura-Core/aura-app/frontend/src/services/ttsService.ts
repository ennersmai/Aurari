/**
 * TTS Service — DEPRECATED
 *
 * This service previously connected to a legacy WebSocket TTS server at
 * `ws://localhost:8001/stream`. That server is no longer part of the Aura
 * architecture.
 *
 * All chat TTS now goes through the backend REST API:
 *   POST /voice/stream   (supports Edge-TTS and CosyVoice with auto-fallback)
 *   GET  /voice/status    (provider availability)
 *   GET  /voice/voices    (available voices per provider)
 *
 * The actual TTS integration lives inline in:
 *   - frontend/src/pages/chat.tsx          (generateAudioForSentence)
 *   - frontend/src/pages/mission-control.tsx
 *
 * This file is kept as a reference for the legacy WebAudio scheduling
 * approach (PCM16 → Float32 → AudioBuffer → scheduled playback) in case
 * a future local streaming TTS engine needs low-level buffer management.
 *
 * DO NOT USE THIS SERVICE FOR NEW CODE.
 * Use `fetch(`${API_BASE_URL}/voice/stream`, { method: 'POST', … })` instead.
 */

import { EventEmitter } from 'events';

// ---- Legacy constants (kept for reference) ----
const LEGACY_TTS_SERVER_URL = 'ws://localhost:8001/stream';
const SAMPLE_RATE = 24000;

export class TTSService extends EventEmitter {
  private audioContext: AudioContext | null = null;
  private isPlaying: boolean = false;
  private audioQueue: Float32Array[] = [];
  private nextStartTime: number = 0;
  private currentSocket: WebSocket | null = null;

  constructor() {
    super();
  }

  private getAudioContext(): AudioContext {
    if (!this.audioContext) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: SAMPLE_RATE,
      });
    }
    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume().catch(e => console.warn("AudioContext resume failed:", e));
    }
    return this.audioContext;
  }

  /** @deprecated Use POST /voice/stream instead. */
  public async speak(text: string, voice?: string): Promise<void> {
    console.warn('[ttsService] speak() is deprecated. Use POST /voice/stream via the backend API.');
    if (!text.trim()) return;

    this.stop();
    this.getAudioContext();
    this.nextStartTime = this.getAudioContext().currentTime;
    this.isPlaying = true;
    this.audioQueue = [];

    const url = new URL(LEGACY_TTS_SERVER_URL);
    url.searchParams.append('text', text);
    url.searchParams.append('voice', voice || 'en-Davis_man');
    url.searchParams.append('cfg', '1.0');
    url.searchParams.append('steps', '3');

    return new Promise((resolve, reject) => {
      this.connectAndStream(url, resolve, reject, true);
    });
  }

  private handleAudioChunk(buffer: ArrayBuffer) {
    this.getAudioContext();
    const int16Array = new Int16Array(buffer);
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768.0;
    }
    this.scheduleBuffer(float32Array);
  }

  private scheduleBuffer(audioData: Float32Array) {
    const ctx = this.getAudioContext();
    const buffer = ctx.createBuffer(1, audioData.length, SAMPLE_RATE);
    const channelData = buffer.getChannelData(0);
    channelData.set(audioData);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);

    const startTime = Math.max(ctx.currentTime, this.nextStartTime);
    source.start(startTime);
    this.nextStartTime = startTime + buffer.duration;
  }

  public stop() {
    if (this.currentSocket) {
      this.currentSocket.close();
      this.currentSocket = null;
    }
    if (this.audioContext) {
      this.audioContext.suspend();
      this.audioContext.close().then(() => {
        this.audioContext = null;
      });
    }
    this.isPlaying = false;
  }

  /** @deprecated Voice list is now available via GET /voice/voices. */
  public getVoices(): string[] {
    console.warn('[ttsService] getVoices() is deprecated. Use GET /voice/voices instead.');
    return [
      'en-Carter_man', 'en-Davis_man', 'en-Emma_woman', 'en-Frank_man',
      'en-Grace_woman', 'en-Mike_man',
      'fr-Spk0_man', 'fr-Spk1_woman',
      'de-Spk0_man', 'de-Spk1_woman',
      'jp-Spk0_man', 'jp-Spk1_woman'
    ];
  }

  /** @deprecated Use streaming via POST /voice/stream per sentence instead. */
  public async streamText(textStream: ReadableStream<string>, voice?: string): Promise<void> {
    console.warn('[ttsService] streamText() is deprecated.');
    this.stop();
    const ctx = this.getAudioContext();
    this.nextStartTime = ctx.currentTime;
    this.isPlaying = true;
    this.audioQueue = [];

    let buffer = "";
    const sentenceEndRegex = /[.!?]+[\s\n\*"]+|[.!?]+(?=[A-Z"*])/;
    const sentenceQueue: string[] = [];
    let isProcessing = false;

    const processSentence = async (sentence: string) => {
      if (!this.isPlaying) return;
      try {
        await this.speakSentence(sentence, voice);
      } catch (err) {
        console.error("Stream TTS error:", err);
      }
    };

    const processQueue = async () => {
      if (isProcessing || sentenceQueue.length === 0) return;
      isProcessing = true;
      while (sentenceQueue.length > 0 && this.isPlaying) {
        const sentence = sentenceQueue.shift();
        if (sentence) await processSentence(sentence);
      }
      isProcessing = false;
    };

    try {
      const reader = textStream.getReader();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (!this.isPlaying) break;
          const chunk = value;
          buffer += chunk;
          let match;
          while ((match = buffer.match(sentenceEndRegex)) !== null) {
            if (match.index === undefined) break;
            const sentence = buffer.substring(0, match.index + match[0].length);
            buffer = buffer.substring(match.index + match[0].length);
            if (sentence.trim()) {
              sentenceQueue.push(sentence);
              processQueue();
            }
          }
        }
      } finally {
        reader.releaseLock();
      }
      if (buffer.trim() && this.isPlaying) {
        sentenceQueue.push(buffer);
        await processQueue();
      }
      while (sentenceQueue.length > 0 && this.isPlaying) {
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    } catch (e) {
      console.error("Error in streamText:", e);
    }
  }

  /** @deprecated */
  private async speakSentence(text: string, voice?: string): Promise<void> {
    const url = new URL(LEGACY_TTS_SERVER_URL);
    url.searchParams.append('text', text);
    url.searchParams.append('voice', voice || 'en-Davis_man');
    url.searchParams.append('cfg', '1.0');
    url.searchParams.append('steps', '3');
    return new Promise((resolve, reject) => {
      this.connectAndStream(url, resolve, reject);
    });
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private connectAndStream(url: URL, resolve: (value?: void) => void, reject: (err: any) => void, isMainSocket: boolean = false) {
    try {
      const socket = new WebSocket(url.toString());
      socket.binaryType = 'arraybuffer';

      if (isMainSocket) {
        this.currentSocket = socket;
      }

      socket.onopen = () => {
        if (isMainSocket) {
          console.log('TTS Socket connected');
          this.emit('start');
        }
      };

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      socket.onmessage = async (event: any) => {
        if (typeof event.data === 'string') {
          // Handle logs if needed
        } else if (event.data instanceof ArrayBuffer) {
          if (this.isPlaying) {
            this.handleAudioChunk(event.data);
          }
        }
      };

      socket.onerror = (error) => {
        console.error('TTS Socket error:', error);
        if (isMainSocket) this.emit('error', error);
        reject(error);
      };

      socket.onclose = () => {
        if (isMainSocket) {
          console.log('TTS Socket closed');
          this.isPlaying = false;
          this.currentSocket = null;
          this.emit('end');
        }
        resolve();
      };

    } catch (error) {
      if (isMainSocket) console.error('Failed to connect to TTS server:', error);
      reject(error);
    }
  }
}

/** @deprecated Use POST /voice/stream via the backend API instead. */
export const ttsService = new TTSService();
