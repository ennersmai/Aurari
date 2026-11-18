"use client";

import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Mic, Upload, Play, Square, Loader2, ChevronDown, ChevronUp,
  CheckCircle2, XCircle, Trash2, User
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { API_BASE_URL } from '@/config';

// --- Qwen3-TTS speakers (mirrors mission-control list) ---
const QWEN3_SPEAKERS = [
  { id: 'serena',     name: 'Serena — Warm, Gentle (Chinese)' },
  { id: 'vivian',     name: 'Vivian — Bright, Edgy (Chinese)' },
  { id: 'uncle_fu',   name: 'Uncle Fu — Mellow (Chinese)' },
  { id: 'ryan',       name: 'Ryan — Dynamic (English)' },
  { id: 'aiden',      name: 'Aiden — Sunny, Clear (English)' },
  { id: 'ono_anna',   name: 'Ono Anna — Playful (Japanese)' },
  { id: 'sohee',      name: 'Sohee — Warm, Rich (Korean)' },
  { id: 'eric',       name: 'Eric — Lively (Sichuan Dialect)' },
  { id: 'dylan',      name: 'Dylan — Youthful (Beijing Dialect)' },
];

export default function VoiceClonePanel() {
  const [isExpanded, setIsExpanded] = useState(false);
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [testText, setTestText] = useState("Hello, I am Aura. This is my voice speaking to you.");
  const [instruct, setInstruct] = useState("");
  const [speaker, setSpeaker] = useState("serena");
  const [language, setLanguage] = useState("english");
  const [isGenerating, setIsGenerating] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const validTypes = ['audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/webm', 'audio/flac'];
      if (!validTypes.some(t => file.type.startsWith(t.split('/')[0]))) {
        setError('Please upload an audio file (WAV, MP3, OGG, FLAC)');
        return;
      }
      if (file.size > 50 * 1024 * 1024) {
        setError('File too large. Maximum 50MB.');
        return;
      }
      setReferenceFile(file);
      setError(null);
      setAudioUrl(null);
    }
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!testText.trim()) return;

    setIsGenerating(true);
    setError(null);
    setAudioUrl(null);

    try {
      // Build JSON payload for /voice/clone
      const payload: Record<string, unknown> = {
        text: testText,
        speaker,
        language,
      };
      if (instruct.trim()) {
        payload.instruct = instruct.trim();
      }

      // If reference audio is provided, encode as base64
      if (referenceFile) {
        const bytes = await referenceFile.arrayBuffer();
        const base64 = btoa(
          Array.from(new Uint8Array(bytes))
            .map(b => String.fromCharCode(b))
            .join('')
        );
        payload.reference_audio = `data:${referenceFile.type};base64,${base64}`;
        payload.reference_text = testText;
      }

      const response = await fetch(`${API_BASE_URL}/voice/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errData.detail || `Failed: ${response.status}`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Voice cloning failed');
    } finally {
      setIsGenerating(false);
    }
  }, [referenceFile, testText, instruct, speaker, language]);

  const handlePlay = useCallback(() => {
    if (!audioUrl) return;

    if (isPlaying && audioRef.current) {
      audioRef.current.pause();
      setIsPlaying(false);
      return;
    }

    const audio = new Audio(audioUrl);
    audioRef.current = audio;
    audio.onended = () => setIsPlaying(false);
    audio.onerror = () => setIsPlaying(false);
    audio.play();
    setIsPlaying(true);
  }, [audioUrl, isPlaying]);

  const handleClear = useCallback(() => {
    setReferenceFile(null);
    setAudioUrl(null);
    setError(null);
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setIsPlaying(false);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full bg-black/40 border border-purple-900/50 rounded-lg backdrop-blur-sm overflow-hidden"
    >
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-purple-900/10 transition-colors"
      >
        <div className="flex items-center gap-3">
          <Mic size={16} className="text-purple-400" />
          <span className="font-mono text-sm text-purple-400">VOICE_CLONING</span>
          {referenceFile && (
            <span className="text-[9px] font-mono px-2 py-0.5 rounded bg-purple-900/30 border border-purple-700/50 text-purple-300">
              REF LOADED
            </span>
          )}
        </div>
        {isExpanded ? <ChevronUp size={16} className="text-purple-400" /> : <ChevronDown size={16} className="text-purple-400" />}
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="border-t border-purple-900/50"
          >
            <div className="p-4 space-y-3">

              {/* Speaker & Language */}
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <label className="flex items-center gap-1 text-[10px] font-mono text-purple-400">
                    <User size={10} /> SPEAKER
                  </label>
                  <select
                    value={speaker}
                    onChange={(e) => setSpeaker(e.target.value)}
                    className="w-full bg-black/50 border border-purple-900/50 rounded px-2 py-1.5 text-[10px] font-mono text-purple-200 focus:outline-none focus:border-purple-500"
                  >
                    {QWEN3_SPEAKERS.map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-mono text-purple-400">LANGUAGE</label>
                  <select
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    className="w-full bg-black/50 border border-purple-900/50 rounded px-2 py-1.5 text-[10px] font-mono text-purple-200 focus:outline-none focus:border-purple-500"
                  >
                    <option value="english">English</option>
                    <option value="chinese">Chinese</option>
                    <option value="japanese">Japanese</option>
                    <option value="korean">Korean</option>
                    <option value="german">German</option>
                    <option value="french">French</option>
                    <option value="russian">Russian</option>
                    <option value="portuguese">Portuguese</option>
                    <option value="spanish">Spanish</option>
                    <option value="italian">Italian</option>
                  </select>
                </div>
              </div>

              {/* Upload Reference Audio */}
              <div className="space-y-2">
                <label className="flex items-center gap-2 text-xs font-mono text-purple-400">
                  <Upload size={12} />
                  <span>REFERENCE_AUDIO (~10s sample)</span>
                </label>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept="audio/*"
                  onChange={handleFileSelect}
                  className="hidden"
                />

                {referenceFile ? (
                  <div className="flex items-center justify-between p-2.5 bg-purple-900/15 border border-purple-800/40 rounded">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 size={14} className="text-green-400" />
                      <span className="text-[11px] font-mono text-purple-200 truncate max-w-[200px]">
                        {referenceFile.name}
                      </span>
                      <span className="text-[9px] text-gray-500">{formatSize(referenceFile.size)}</span>
                    </div>
                    <button onClick={handleClear} className="p-1 text-red-400 hover:text-red-300">
                      <Trash2 size={12} />
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="w-full p-4 border-2 border-dashed border-purple-800/40 rounded-lg text-center hover:bg-purple-900/10 hover:border-purple-700/50 transition-colors"
                  >
                    <Upload size={20} className="mx-auto text-purple-500 mb-1" />
                    <div className="text-[11px] font-mono text-purple-400">Click to upload reference audio</div>
                    <div className="text-[9px] text-gray-600 mt-0.5">WAV, MP3, OGG — ~10 second clip of target voice</div>
                  </button>
                )}
              </div>

              {/* Test Text */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-purple-400">TEST_TEXT</label>
                <textarea
                  value={testText}
                  onChange={(e) => setTestText(e.target.value)}
                  rows={2}
                  className="w-full bg-black/50 border border-purple-900/50 rounded px-3 py-2 text-purple-200 placeholder-purple-900/60 focus:outline-none focus:border-purple-500 font-mono text-[11px] resize-none"
                  placeholder="Text to speak in the cloned voice..."
                />
              </div>

              {/* Emotional Instruction */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-purple-400">EMOTION_INSTRUCT (optional)</label>
                <input
                  type="text"
                  value={instruct}
                  onChange={(e) => setInstruct(e.target.value)}
                  className="w-full bg-black/50 border border-purple-900/50 rounded px-3 py-1.5 text-purple-200 placeholder-purple-900/60 focus:outline-none focus:border-purple-500 font-mono text-[11px]"
                  placeholder="e.g., Speak with warmth and curiosity"
                />
              </div>

              {/* Generate + Play Buttons */}
              <div className="flex gap-2">
                <button
                  onClick={handleGenerate}
                  disabled={!testText.trim() || isGenerating}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded font-mono text-sm transition-all",
                    testText.trim() && !isGenerating
                      ? "bg-purple-900/30 border border-purple-700 text-purple-400 hover:bg-purple-800/50"
                      : "bg-gray-900/30 border border-gray-800 text-gray-600 cursor-not-allowed"
                  )}
                >
                  {isGenerating ? (
                    <><Loader2 size={14} className="animate-spin" /> GENERATING...</>
                  ) : (
                    <><Mic size={14} /> GENERATE</>
                  )}
                </button>

                {audioUrl && (
                  <button
                    onClick={handlePlay}
                    className={cn(
                      "px-4 py-2 rounded border transition-colors",
                      isPlaying
                        ? "bg-green-900/30 border-green-700/50 text-green-400"
                        : "bg-purple-900/20 border-purple-700/50 text-purple-400 hover:bg-purple-900/40"
                    )}
                  >
                    {isPlaying ? <Square size={14} /> : <Play size={14} />}
                  </button>
                )}
              </div>

              {/* Error Display */}
              {error && (
                <div className="flex items-center gap-2 p-2 bg-red-900/20 border border-red-900/40 rounded text-[10px] font-mono text-red-400">
                  <XCircle size={12} />
                  {error}
                </div>
              )}

              {/* Info */}
              <div className="p-2 bg-purple-900/10 border border-purple-900/30 rounded text-[9px] font-mono text-purple-300/60">
                Uses Qwen3-TTS for voice generation. Upload a ~10s voice sample
                for instruct-based style steering (CustomVoice model) or zero-shot
                cloning (requires Base model). Emotional instructions steer the
                tone/mood of generated speech across 9 built-in speakers.
              </div>

            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
