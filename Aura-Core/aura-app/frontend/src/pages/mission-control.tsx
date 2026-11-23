"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/router";
import { motion, AnimatePresence } from "framer-motion";
import NeuralSidebar from "@/components/neural/NeuralSidebar";
import CognitiveStatus from "@/components/cognitive/CognitiveStatus";
import SettingsPanel from "@/components/settings/SettingsPanel";
import AIProviderPanel from "@/components/settings/AIProviderPanel";
import AgentLoopPanel from "@/components/agent/AgentLoopPanel";
import VoiceClonePanel from "@/components/voice/VoiceClonePanel";
import CulturalPanel from "@/components/cultural/CulturalPanel";
import MemoryIntrospectionPanel from "@/components/memory/MemoryIntrospectionPanel";
import InferenceCockpit from "@/components/inference/InferenceCockpit";
import { useInferenceConfig } from "@/hooks/useInferenceConfig";
import { AuraStatus, ChatMessage, EmotionState, Memory, WebSocketEvent } from "@/types/aura";
import { Send, Terminal, Power, Activity, Maximize2, Minimize2, Target, ArrowLeft, MessageSquare, Volume2, VolumeX, Settings, Server } from "lucide-react";
import { cn } from "@/lib/utils";
import { auraApi } from "@/services/auraApiService";
import { SettingsProvider, useSettings } from "@/contexts/SettingsContext";
import { API_BASE_URL } from "@/config";

function MissionControlContent() {
  const router = useRouter();
  const { settings } = useSettings();
  const { config: inferCfg, applyNow: applyInferNow } = useInferenceConfig();
  const [input, setInput] = useState("");
  const [expandedPanel, setExpandedPanel] = useState<'emotion' | 'cognitive' | 'memory' | 'goals' | null>(null);
  const [isVoiceEnabled, setIsVoiceEnabled] = useState(false);
  const [selectedVoice, setSelectedVoice] = useState('en-US-MichelleNeural');
  const [ttsProvider, setTtsProvider] = useState<'edge' | 'qwen3' | 'fishaudio'>('edge');
  const [voiceMenuAnchor, setVoiceMenuAnchor] = useState<null | HTMLElement>(null);

  // Qwen3-TTS config state
  const [qwenSpeaker, setQwenSpeaker] = useState('serena');
  const [qwenInstruct, setQwenInstruct] = useState('');
  const [qwenTemperature, setQwenTemperature] = useState(0.9);
  const [qwenTopP, setQwenTopP] = useState(1.0);
  const [qwenTopK, setQwenTopK] = useState(50);

  const qwen3Speakers = [
    { id: 'serena',     name: 'Serena (Warm, Gentle — Chinese)' },
    { id: 'vivian',     name: 'Vivian (Bright, Edgy — Chinese)' },
    { id: 'uncle_fu',   name: 'Uncle Fu (Mellow, Seasoned — Chinese)' },
    { id: 'ryan',       name: 'Ryan (Dynamic, Rhythmic — English)' },
    { id: 'aiden',      name: 'Aiden (Sunny, Clear — English)' },
    { id: 'ono_anna',   name: 'Ono Anna (Playful, Nimble — Japanese)' },
    { id: 'sohee',      name: 'Sohee (Warm, Rich — Korean)' },
    { id: 'eric',       name: 'Eric (Lively, Husky — Sichuan Dialect)' },
    { id: 'dylan',      name: 'Dylan (Youthful, Clear — Beijing Dialect)' },
  ];

  const edgeTTSVoices = [
    { id: 'en-US-AriaNeural', name: 'Aria (US Female, Friendly)' },
    { id: 'en-US-GuyNeural', name: 'Guy (US Male, Casual)' },
    { id: 'en-US-JennyNeural', name: 'Jenny (US Female, Assistant)' },
    { id: 'en-US-EricNeural', name: 'Eric (US Male, News)' },
    { id: 'en-US-MichelleNeural', name: 'Michelle (US Female, Expressive)' },
    { id: 'en-GB-SoniaNeural', name: 'Sonia (British Female)' },
    { id: 'en-GB-RyanNeural', name: 'Ryan (British Male)' },
    { id: 'en-AU-NatashaNeural', name: 'Natasha (Australian Female)' },
    { id: 'en-AU-WilliamNeural', name: 'William (Australian Male)' },
  ];

  const [status, setStatus] = useState<AuraStatus>({
    online: true,
    emotion: {
      love: 0.2, joy: 0.3, interest: 0.4, trust: 0.3, fear: 0.1,
      sadness: 0.1, anger: 0.0, surprise: 0.1, disgust: 0.0,
      awe: 0.2, beauty: 0.15, wonder: 0.25, serenity: 0.2,
      melancholy: 0.1, nostalgia: 0.1,
      empathy: 0.3, gratitude: 0.2, pride: 0.1, shame: 0.0, envy: 0.0, compassion: 0.25,
      curiosity: 0.4, confusion: 0.1, certainty: 0.2, doubt: 0.1, fascination: 0.3, boredom: 0.0,
      anticipation: 0.4,
      current_state: "CURIOSITY",
      dominant: "curiosity",
      valence: 0.3, arousal: 0.4, entropy: 0.15, inertia: 0.2,
    },
    cognitive: {
      layer: 'L1', status: 'idle', model: 'mistralai/mistral-7b-instruct', latency_ms: 0,
    },
    last_memory: null, active_goals: [],
    identity_snapshot: "I am Aura, an evolving AI companion.",
    database_connected: true, total_interactions: 0,
  });

  const [chatLog, setChatLog] = useState<ChatMessage[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  
  // FIX #2: Track mounted state to prevent state updates after unmount
  const isMountedRef = useRef(true);
  
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);
  
  // FIX #1: Refs to avoid stale closures in handleSend
  const chatLogRef = useRef(chatLog);
  const statusRef = useRef(status);
  const settingsRef = useRef(settings);
  const isVoiceEnabledRef = useRef(isVoiceEnabled);
  const ttsProviderRef = useRef(ttsProvider);
  const selectedVoiceRef = useRef(selectedVoice);
  const qwenSpeakerRef = useRef(qwenSpeaker);
  const qwenInstructRef = useRef(qwenInstruct);
  
  useEffect(() => { chatLogRef.current = chatLog; }, [chatLog]);
  useEffect(() => { statusRef.current = status; }, [status]);
  useEffect(() => { settingsRef.current = settings; }, [settings]);
  useEffect(() => { isVoiceEnabledRef.current = isVoiceEnabled; }, [isVoiceEnabled]);
  useEffect(() => { ttsProviderRef.current = ttsProvider; }, [ttsProvider]);
  useEffect(() => { selectedVoiceRef.current = selectedVoice; }, [selectedVoice]);
  useEffect(() => { qwenSpeakerRef.current = qwenSpeaker; }, [qwenSpeaker]);
  useEffect(() => { qwenInstructRef.current = qwenInstruct; }, [qwenInstruct]);

  const fetchStatus = useCallback(async () => {
    try {
      const systemStatus = await auraApi.getSystemStatus();
      setIsConnected(systemStatus.healthy);
      setStatus(prev => ({
        ...prev,
        online: systemStatus.healthy,
        database_connected: systemStatus.database,
      }));
    } catch (error) {
      console.error('Failed to fetch status:', error);
      setIsConnected(false);
      setStatus(prev => ({ ...prev, online: false, database_connected: false }));
    }
  }, []);

  const fetchEmotionState = useCallback(async () => {
    try {
      const emotionData = await auraApi.getEmotionState();
      setStatus(prev => ({ ...prev, emotion: emotionData }));
    } catch (error) {
      console.error('Failed to fetch emotion state:', error);
    }
  }, []);

  const fetchGoals = useCallback(async () => {
    try {
      const goals = await auraApi.getActiveGoals();
      setStatus(prev => ({ ...prev, active_goals: goals }));
    } catch (error) {
      console.error('Failed to fetch goals:', error);
    }
  }, []);

  const fetchMemories = useCallback(async () => {
    try {
      const memoriesData = await auraApi.getRecentMemories(10, settings.commanderIdentity);
      setMemories(memoriesData);
    } catch (error) {
      console.error('Failed to fetch memories:', error);
    }
  }, [settings.commanderIdentity]);

  // FIX #2: Track heartbeat interval per WebSocket connection
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  
  useEffect(() => {
    let reconnectTimeout: NodeJS.Timeout | null = null;

    const connectWebSocket = () => {
      // Track if this connection is still current
      const connectionId = {};
      let currentConnection = connectionId;
      
      try {
        const ws = auraApi.createEmotionWebSocket();
        wsRef.current = ws;

        ws.onopen = () => {
          setIsConnected(true);
          // Clear any stale interval from previous connection
          if (heartbeatIntervalRef.current) {
            clearInterval(heartbeatIntervalRef.current);
          }
          heartbeatIntervalRef.current = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ command: 'heartbeat' }));
            }
          }, 25000);
        };

        ws.onmessage = (event) => {
          try {
            const message: WebSocketEvent = JSON.parse(event.data);
            if (message.type === 'emotion_update' && message.data) {
              setStatus(prev => ({ ...prev, emotion: message.data as EmotionState }));
            }
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };

        ws.onerror = () => { setIsConnected(false); };
        ws.onclose = () => {
          // Only reconnect if this is still the current connection
          if (currentConnection === connectionId && isMountedRef.current) {
            setIsConnected(false);
            // Clear heartbeat for this connection
            if (heartbeatIntervalRef.current) {
              clearInterval(heartbeatIntervalRef.current);
              heartbeatIntervalRef.current = null;
            }
            reconnectTimeout = setTimeout(connectWebSocket, 5000);
          }
        };
      } catch (error) {
        console.error('Failed to create WebSocket:', error);
        if (isMountedRef.current) {
          setIsConnected(false);
          reconnectTimeout = setTimeout(connectWebSocket, 5000);
        }
      }
    };

    connectWebSocket();
    return () => {
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      // Clear heartbeat interval
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = null;
      }
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    };
  }, []);

  useEffect(() => {
    fetchStatus(); fetchEmotionState(); fetchMemories(); fetchGoals();
    const statusInterval = setInterval(fetchStatus, 30000);
    const memoriesInterval = setInterval(fetchMemories, 120000);
    const goalsInterval = setInterval(fetchGoals, 60000);
    return () => { clearInterval(statusInterval); clearInterval(memoriesInterval); clearInterval(goalsInterval); };
  }, [fetchStatus, fetchEmotionState, fetchMemories, fetchGoals]);

  // FIX #3: Track in-flight request to prevent race conditions
  const activeRequestRef = useRef<{ aborted: boolean }>({ aborted: false });
  
  const handleSend = async () => {
    if (!input.trim()) return;
    
    // FIX #3: Abort any previous in-flight request
    activeRequestRef.current.aborted = true;
    const currentRequest = { aborted: false };
    activeRequestRef.current = currentRequest;
    
    const userMessage: ChatMessage = { id: `msg-${Date.now()}`, role: 'user', content: input, timestamp: new Date().toISOString() };
    const messageContent = input;
    setInput("");
    setChatLog(prev => [...prev, userMessage]);

    const startTime = Date.now();
    setStatus(prev => ({ ...prev, cognitive: { ...prev.cognitive, status: 'processing', layer: 'L3' } }));

    const textBuffer = { current: '' };
    const audioQueue: Blob[] = [];
    const isPlaying = { current: false };
    const sentenceEndRegex = /[.!?]\s+$/;

    // --- FIFO Sentence Queue: prevents async racing where shorter sentences
    //     resolve before longer preceding ones, causing out-of-order playback.
    const sentenceQueue: string[] = [];
    let isProcessingQueue = false;

    const processSentenceQueue = async () => {
      if (isProcessingQueue) return;
      isProcessingQueue = true;
      while (sentenceQueue.length > 0) {
        // FIX #3: Check for abort between queue items
        if (activeRequestRef.current.aborted) return;
        const sentence = sentenceQueue.shift()!;
        await generateAudioForSentence(sentence);
      }
      isProcessingQueue = false;
    };
    // -------------------------------------------------------------------

    const sanitizeText = (text: string): string => text.replace(/\*/g, '').replace(/[()]/g, '').replace(/[_]{1,2}/g, '').trim();

    const playNextInQueue = () => {
      if (isPlaying.current || audioQueue.length === 0) return;
      isPlaying.current = true;
      const audioBlob = audioQueue.shift()!;
      const url = URL.createObjectURL(audioBlob);
      const audio = new Audio(url);
      audio.onended = () => { URL.revokeObjectURL(url); isPlaying.current = false; playNextInQueue(); };
      audio.onerror = () => { URL.revokeObjectURL(url); isPlaying.current = false; playNextInQueue(); };
      audio.play().catch(() => { URL.revokeObjectURL(url); isPlaying.current = false; playNextInQueue(); });
    };

    // FIX #1: Use refs for values accessed in closures to avoid stale data
    const generateAudioForSentence = async (sentence: string) => {
      if (!isVoiceEnabledRef.current) return;
      const cleaned = sanitizeText(sentence);
      if (cleaned.length < 2) return;

      const buildPayload = (provider: 'edge' | 'qwen3' | 'fishaudio'): Record<string, unknown> => {
        if (provider === 'qwen3') {
          return {
            text: cleaned,
            voice: qwenSpeakerRef.current,
            provider: 'qwen3',
            instruct: qwenInstructRef.current || undefined,
            emotion_state: {
              dominant: statusRef.current.emotion?.dominant || 'neutral',
              valence: statusRef.current.emotion?.valence || 0,
              arousal: statusRef.current.emotion?.arousal || 0.5,
            },
          };
        }
        if (provider === 'fishaudio') {
          return {
            text: cleaned,
            voice: 'default',
            provider: 'fishaudio',
          };
        }
        return { text: cleaned, voice: selectedVoiceRef.current, provider: 'edge' };
      };

      const tryTTS = async (provider: 'edge' | 'qwen3' | 'fishaudio'): Promise<{ blob: Blob; actualProvider: string } | null> => {
        try {
          const voiceResponse = await fetch(`${API_BASE_URL}/voice/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildPayload(provider)) });
          if (voiceResponse.ok) {
            const blob = await voiceResponse.blob();
            const actualProvider = voiceResponse.headers.get('X-TTS-Provider') || provider;
            return { blob, actualProvider };
          }
          return null;
        } catch { return null; }
      };

      let result = await tryTTS(ttsProviderRef.current);
      if (!result && (ttsProviderRef.current === 'qwen3' || ttsProviderRef.current === 'fishaudio')) {
        // Local TTS unavailable — fall back to Edge-TTS
        result = await tryTTS('edge');
        if (result && isMountedRef.current && !currentRequest.aborted) {
          setChatLog(prev => [...prev, { id: `msg-${Date.now()}`, role: 'system', content: '\u26A0\uFE0F Qwen3-TTS (local) is unavailable. Using Edge-TTS (cloud) instead.', timestamp: new Date().toISOString() }]);
        }
      }
      if (result) { audioQueue.push(result.blob); playNextInQueue(); }
    };

    try {
      // FIX #1: Use ref for chatLog to get current value
      const conversationHistory = chatLogRef.current.map(msg => ({ role: msg.role === 'aura' ? 'assistant' : msg.role, content: msg.content }));
      // FIX #1: Use ref for settings
      const response = await auraApi.sendMessage({
        message: messageContent, user_id: settingsRef.current.commanderIdentity, conversation_history: conversationHistory,
        context_limit: settingsRef.current.contextWindowSize,
        onToken: async (token) => {
          // FIX #3: Check abort during streaming
          if (activeRequestRef.current.aborted) return;
          textBuffer.current += token;
          if (sentenceEndRegex.test(textBuffer.current)) {
            const sentence = textBuffer.current; textBuffer.current = '';
            sentenceQueue.push(sentence);
            processSentenceQueue();
          }
        }
      });

      // FIX #3: Check if request was aborted before updating state
      if (currentRequest.aborted || !isMountedRef.current) return;

      const latency = Date.now() - startTime;
      // FIX #1: Use ref for status to get current emotion state
      const auraMessage: ChatMessage = {
        id: `msg-${Date.now()}`, role: 'aura', content: response.response, timestamp: new Date().toISOString(),
        cognitive_layer: 'L3',
        emotional_state: response.emotional_state ? { ...statusRef.current.emotion, dominant: response.emotional_state.dominant, current_state: response.emotional_state.description } : undefined,
      };
      setChatLog(prev => [...prev, auraMessage]);
      setStatus(prev => ({ ...prev, cognitive: { ...prev.cognitive, status: 'idle', layer: 'L1', latency_ms: latency }, total_interactions: (prev.total_interactions || 0) + 1 }));
      
      // FIX #4: Only call fetchMemories if component is still mounted
      if (isMountedRef.current) {
        fetchMemories();
      }
      
      if (textBuffer.current.trim().length > 0) { await generateAudioForSentence(textBuffer.current); }
    } catch (error) {
      // FIX #3: Check if aborted before handling error
      if (currentRequest.aborted) return;
      
      console.error('Failed to send message:', error);
      if (isMountedRef.current) {
        setChatLog(prev => [...prev, { id: `msg-${Date.now()}`, role: 'system', content: `Error: ${error instanceof Error ? error.message : 'Failed to send message'}`, timestamp: new Date().toISOString() }]);
        setStatus(prev => ({ ...prev, cognitive: { ...prev.cognitive, status: 'idle', layer: 'L1' } }));
      }
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } };

  return (
    <main className="min-h-screen text-green-500 font-sans selection:bg-amber-500/30 selection:text-white flex flex-col overflow-hidden" style={{ background: '#060608' }}>
      {/* Glass background texture */}
      <div className="fixed inset-0 pointer-events-none z-0" style={{
        background: 'radial-gradient(ellipse at 50% 0%, rgba(192,156,88,0.04) 0%, transparent 60%), radial-gradient(ellipse at 80% 80%, rgba(74,222,128,0.03) 0%, transparent 50%)',
      }} />

      {/* Voice Selection Menu */}
      {voiceMenuAnchor && (
        <div className="fixed inset-0 z-50" onClick={() => setVoiceMenuAnchor(null)}>
          <div
            className="absolute glass-panel p-3 min-w-[340px] max-h-[80vh] overflow-y-auto glass-scrollbar"
            style={{ top: voiceMenuAnchor.getBoundingClientRect().bottom + 8, left: voiceMenuAnchor.getBoundingClientRect().left }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* TTS Provider Tabs */}
            <div className="flex gap-1 mb-2">
              <button onClick={() => { setTtsProvider('edge'); setSelectedVoice('en-US-MichelleNeural'); }}
                className={cn("flex-1 px-3 py-1.5 rounded-md text-xs font-mono transition-all",
                  ttsProvider === 'edge' ? "glass-btn-accent text-[11px]" : "glass-btn text-gray-500 text-[11px]")}>
                EDGE
              </button>
              <button onClick={() => { setTtsProvider('qwen3'); setSelectedVoice('serena'); }}
                className={cn("flex-1 px-3 py-1.5 rounded-md text-xs font-mono transition-all",
                  ttsProvider === 'qwen3' ? "glass-btn-accent text-[11px]" : "glass-btn text-gray-500 text-[11px]")}>
                QWEN3
              </button>
              <button onClick={() => { setTtsProvider('fishaudio'); setSelectedVoice('default'); }}
                className={cn("flex-1 px-3 py-1.5 rounded-md text-xs font-mono transition-all",
                  ttsProvider === 'fishaudio' ? "glass-btn-accent text-[11px]" : "glass-btn text-gray-500 text-[11px]")}>
                FISH
              </button>
            </div>
            <hr className="glass-divider my-1.5" />

            {ttsProvider === 'edge' ? (
              /* Edge-TTS voice list */
              edgeTTSVoices.map((voice) => (
                <button key={voice.id} onClick={() => { setSelectedVoice(voice.id); setVoiceMenuAnchor(null); }}
                  className={cn("w-full text-left px-3 py-2 rounded-md text-xs transition-all",
                    voice.id === selectedVoice ? "bg-amber-500/10 text-amber-300 font-medium" : "text-green-400/70 hover:bg-white/[0.04]")}>
                  {voice.name}
                </button>
              ))
            ) : ttsProvider === 'qwen3' ? (
              /* Qwen3-TTS controls */
              <>
                {/* Speaker selection */}
                <div className="mb-2">
                  <div className="text-[10px] text-gray-500 font-mono mb-1">SPEAKER</div>
                  <div className="grid grid-cols-2 gap-1">
                    {qwen3Speakers.map((spk) => (
                      <button key={spk.id} onClick={() => { setQwenSpeaker(spk.id); setSelectedVoice(spk.id); }}
                        className={cn("text-left px-2 py-1.5 rounded text-[10px] font-mono transition-all",
                          qwenSpeaker === spk.id ? "bg-violet-500/10 text-violet-300 border border-violet-500/25" : "text-gray-500 hover:bg-white/[0.04]")}>
                        {spk.name}
                      </button>
                    ))}
                  </div>
                </div>

                <hr className="glass-divider my-1.5" />

                {/* Emotion Instruct */}
                <div className="mb-2">
                  <div className="text-[10px] text-gray-500 font-mono mb-1">EMOTION INSTRUCT</div>
                  <input
                    type="text"
                    value={qwenInstruct}
                    onChange={(e) => setQwenInstruct(e.target.value)}
                    placeholder="e.g., Speak warmly and gently..."
                    className="w-full bg-black/50 border border-white/[0.06] rounded px-2 py-1 text-[10px] font-mono text-gray-300 placeholder-gray-600 focus:outline-none focus:border-violet-500/40"
                  />
                </div>

                {/* Generation Config */}
                <div className="text-[10px] text-gray-500 font-mono mb-1">GENERATION CONFIG</div>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] text-gray-600 w-16 shrink-0">Temperature</span>
                    <input type="range" min="0.1" max="2.0" step="0.05" value={qwenTemperature}
                      onChange={(e) => setQwenTemperature(parseFloat(e.target.value))}
                      className="flex-1 h-1 accent-violet-500" />
                    <span className="text-[9px] text-violet-400 w-8 text-right">{qwenTemperature.toFixed(2)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] text-gray-600 w-16 shrink-0">Top-P</span>
                    <input type="range" min="0.1" max="1.0" step="0.05" value={qwenTopP}
                      onChange={(e) => setQwenTopP(parseFloat(e.target.value))}
                      className="flex-1 h-1 accent-violet-500" />
                    <span className="text-[9px] text-violet-400 w-8 text-right">{qwenTopP.toFixed(2)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] text-gray-600 w-16 shrink-0">Top-K</span>
                    <input type="range" min="1" max="200" step="1" value={qwenTopK}
                      onChange={(e) => setQwenTopK(parseInt(e.target.value))}
                      className="flex-1 h-1 accent-violet-500" />
                    <span className="text-[9px] text-violet-400 w-8 text-right">{qwenTopK}</span>
                  </div>
                </div>

                <hr className="glass-divider my-1.5" />

                <button
                  onClick={async () => {
                    try {
                      await fetch(`${API_BASE_URL}/voice/config`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          temperature: qwenTemperature,
                          top_p: qwenTopP,
                          top_k: qwenTopK,
                        }),
                      });
                    } catch {}
                    setVoiceMenuAnchor(null);
                  }}
                  className="w-full mt-1 glass-btn-accent text-[10px] font-mono py-1.5">
                  APPLY CONFIG
                </button>

                <div className="mt-2 p-2 bg-violet-900/10 border border-violet-900/30 rounded text-[8px] font-mono text-violet-300/60">
                  Qwen3-TTS uses emotion-driven synthesis with 9 built-in speakers.
                  Instruct text steers tone and emotion. Requires the Qwen3-TTS server
                  on port 50000. Falls back to Edge-TTS if unavailable.
                </div>
              </>
            ) : (
              /* FishAudio controls */
              <>
                <div className="mb-2 p-2 bg-orange-900/10 border border-orange-900/30 rounded text-[8px] font-mono text-orange-300/60">
                  FishAudio uses fish-speech-1.5 with multi-speaker support and
                  zero-shot voice cloning. Requires the FishAudio server
                  on port 50001. Falls back to Edge-TTS if unavailable.
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* HEADER — Liquid Glass */}
      <motion.header
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        className="glass-toolbar border-b border-white/[0.06] p-4 flex justify-between items-center z-10 shrink-0"
      >
        <div className="flex items-center gap-3">
          <button onClick={() => router.push('/chat')}
            className="glass-btn-icon w-9 h-9" title="Back to Chat">
            <ArrowLeft size={18} />
          </button>
          <Terminal className="text-emerald-400/80" size={22} />
          <div>
            <h1 className="font-bold tracking-widest text-base">
              PROJECT AURA{' '}
              <span className="text-[10px] text-gray-500 font-mono">v0.3.0</span>
            </h1>
            <div className="text-[9px] font-mono text-gray-600">{status.identity_snapshot}</div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button onClick={() => router.push('/chat')} className="glass-btn text-xs">
            <MessageSquare size={14} /> CHAT
          </button>
          <button onClick={() => router.push('/ide')} className="glass-btn text-xs" style={{ borderColor: 'rgba(251,191,36,0.2)', color: '#fbbf24' }}>
            <Terminal size={14} /> IDE
          </button>

          {/* Model Stack Selector — Lean / Core / Titan */}
          <div className="flex gap-0.5 border border-white/[0.06] rounded-lg p-0.5" style={{ background: 'rgba(255,255,255,0.02)' }}>
            {(['LEAN', 'CORE', 'TITAN'] as const).map((label, idx) => {
              const active = inferCfg.model_stack_index === idx;
              const colors = [
                { active: 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400', inactive: 'text-gray-700' },
                { active: 'bg-amber-500/10 border-amber-500/25 text-amber-400',       inactive: 'text-gray-700' },
                { active: 'bg-violet-500/10 border-violet-500/25 text-violet-400',    inactive: 'text-gray-700' },
              ];
              return (
                <button
                  key={label}
                  onClick={() => applyInferNow({ model_stack_index: idx })}
                  className={cn(
                    "px-2 py-0.5 rounded text-[9px] font-mono font-bold transition-all border",
                    active ? colors[idx].active : `border-transparent ${colors[idx].inactive}`,
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>

          {/* Local inference toggle */}
          <button
            onClick={() => applyInferNow({ local_mode_enabled: !inferCfg.local_mode_enabled })}
            className={cn(
              "flex items-center gap-1 text-[10px] font-mono px-2 py-1 rounded-lg border transition-all",
              inferCfg.local_mode_enabled
                ? "bg-violet-500/10 border-violet-500/25 text-violet-300"
                : "glass-btn text-gray-600",
            )}
            title="Toggle local Ollama / SGLang inference"
          >
            <Server size={10} />
            {inferCfg.sglang_enabled ? 'SGLANG' : 'LOCAL'}
          </button>

          {isVoiceEnabled && (
            <button onClick={(e) => setVoiceMenuAnchor(e.currentTarget)}
              className={cn("glass-btn text-xs", ttsProvider !== 'edge' ? "glass-btn-accent" : "")}>
              <Settings size={14} /> {ttsProvider === 'fishaudio' ? 'FISHAUDIO' : ttsProvider === 'qwen3' ? 'QWEN3-TTS' : 'EDGE-TTS'}
            </button>
          )}

          <button onClick={() => setIsVoiceEnabled(!isVoiceEnabled)}
            className={cn("glass-btn-icon w-9 h-9", isVoiceEnabled && "glass-btn-icon-active")}>
            {isVoiceEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
          </button>

          <div className="flex items-center gap-2 text-[10px] font-mono ml-1">
            <span className={cn("glass-status-dot", isConnected ? "glass-status-online" : "glass-status-offline")} />
            <span className="text-gray-500">SYS:</span>
            <span className={isConnected ? 'text-emerald-400' : 'text-red-400'}>{isConnected ? 'ONLINE' : 'OFFLINE'}</span>
          </div>

          <div className="flex items-center gap-2 text-[10px] font-mono">
            <span className={cn("glass-status-dot", status.database_connected ? "glass-status-online" : "glass-status-offline")} />
            <span className="text-gray-500">DB:</span>
            <span className={status.database_connected ? 'text-emerald-400' : 'text-red-400'}>{status.database_connected ? 'CONNECTED' : 'DISCONNECTED'}</span>
          </div>

          {status.total_interactions !== undefined && status.total_interactions > 0 && (
            <div className="text-[10px] font-mono text-gray-500 ml-1">
              INT: <span className="text-emerald-400">{status.total_interactions}</span>
            </div>
          )}
        </div>
      </motion.header>

      {/* SETTINGS & PANELS — Glass Clusters */}
      <div className="px-4 pt-3 space-y-2 shrink-0">
        <InferenceCockpit />
        <SettingsPanel />
        <AIProviderPanel />
        <AgentLoopPanel />
        <VoiceClonePanel />
        <CulturalPanel />
        <MemoryIntrospectionPanel />
      </div>

      {/* DASHBOARD GRID */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-4 p-4 overflow-hidden min-h-0">
        {/* LEFT: NEURAL OBSERVATORY */}
        <motion.div
          initial={{ x: -40, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ delay: 0.1 }}
          className={cn("overflow-hidden min-h-0", expandedPanel ? "hidden lg:block" : "lg:col-span-1")}
        >
          <NeuralSidebar emotion={status.emotion} memories={memories} onRefreshMemories={fetchMemories} />
        </motion.div>

        {/* MIDDLE: COGNITIVE + GOALS */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className={cn("space-y-4 overflow-y-auto glass-scrollbar min-h-0", expandedPanel ? "hidden lg:block" : "lg:col-span-1")}
        >
          {/* Cognitive Status */}
          <div className={cn("relative", expandedPanel === 'cognitive' ? "fixed inset-4 z-50 glass-panel" : "")}>
            <button
              onClick={() => setExpandedPanel(expandedPanel === 'cognitive' ? null : 'cognitive')}
              className="absolute top-2 right-2 z-20 glass-btn-icon w-7 h-7"
              title={expandedPanel === 'cognitive' ? "Minimize" : "Expand"}
            >
              {expandedPanel === 'cognitive' ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <CognitiveStatus trace={status.cognitive} showMetrics={true} />
          </div>

          {/* Goals Panel — Liquid Glass */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
            className={cn("relative glass-panel-sm p-3", expandedPanel === 'goals' ? "fixed inset-4 z-50 flex flex-col" : "")}
            style={{ borderColor: 'rgba(168,85,247,0.15)' }}
          >
            <button
              onClick={() => setExpandedPanel(expandedPanel === 'goals' ? null : 'goals')}
              className="absolute top-2 right-2 z-20 glass-btn-icon w-7 h-7"
              title={expandedPanel === 'goals' ? "Minimize" : "Expand"}
            >
              {expandedPanel === 'goals' ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <div className="flex items-center gap-2 mb-3">
              <Target size={14} className="text-violet-400" />
              <h3 className="text-xs font-mono font-bold tracking-wider text-violet-400/90">GOAL_ENGINE</h3>
            </div>
            <div className="text-[10px] font-mono space-y-2">
              <div><span className="text-gray-500">ACTIVE_GOALS:</span>{' '}<span className="text-violet-300 font-bold">{status.active_goals.length}</span></div>
              {status.active_goals.length > 0 ? (
                <div className={cn("space-y-2 overflow-y-auto glass-scrollbar", expandedPanel === 'goals' ? "flex-1 max-h-none" : "max-h-80")}>
                  {status.active_goals.map((goal) => (
                    <div key={goal.goal_id}
                      className="p-2 rounded-lg text-[9px] group transition-colors"
                      style={{ background: 'rgba(139,92,246,0.05)', border: '1px solid rgba(139,92,246,0.12)' }}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-bold text-violet-300 flex-1 break-words">{goal.name}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-violet-500">{(goal.priority * 100).toFixed(0)}%</span>
                          <button
                            onClick={async () => { if (confirm(`Delete goal "${goal.name}"?`)) { try { await auraApi.deleteGoal(goal.goal_id); fetchGoals(); } catch {} } }}
                            className="opacity-0 group-hover:opacity-100 transition-opacity text-red-400 hover:text-red-300">×</button>
                        </div>
                      </div>
                      <div className="text-gray-400 text-[8px] mb-1 break-words whitespace-pre-wrap">{goal.description}</div>
                      <div className="flex items-center justify-between text-[7px] text-gray-500">
                        <span>{goal.goal_type}</span><span>{Math.round(goal.progress * 100)}% complete</span>
                      </div>
                      {(() => { const r = goal.metadata?.reasoning; return r && typeof r === 'string' ? <div className="text-[7px] text-gray-600 mt-1 italic break-words whitespace-pre-wrap">{r}</div> : null; })()}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[9px] text-gray-500 py-4 text-center">No active goals. Waiting for goal generation...</div>
              )}
              <button onClick={async () => { const newGoal = await auraApi.generateGoal('user_requested'); if (newGoal) fetchGoals(); }}
                className="w-full mt-2 glass-btn glass-btn-accent text-[10px] justify-center py-1.5">+ GENERATE GOAL</button>
            </div>
          </motion.div>
        </motion.div>

        {/* RIGHT: CHAT INTERFACE — Liquid Glass */}
        <motion.div
          initial={{ x: 40, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ delay: 0.2 }}
          className={cn("glass-panel flex flex-col overflow-hidden min-h-0", expandedPanel ? "lg:col-span-4" : "lg:col-span-2")}
          style={{ borderColor: 'rgba(74,222,128,0.12)' }}
        >
          {/* Chat Messages */}
          <div className="flex-1 p-4 overflow-y-auto space-y-4 glass-scrollbar">
            <AnimatePresence mode="popLayout">
              {chatLog.length === 0 ? (
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                  className="flex items-center justify-center h-full">
                  <div className="text-center space-y-4 max-w-md">
                    <Power size={40} className="mx-auto text-emerald-700 animate-pulse" />
                    <h2 className="text-lg font-bold text-emerald-400 font-mono tracking-wider">SYSTEM INITIALIZED</h2>
                    <p className="text-xs text-gray-500 font-mono leading-relaxed">
                      {'>'} 27D Emotion Engine: <span className="text-emerald-500">ONLINE</span><br />
                      {'>'} Learning System: <span className="text-emerald-500">READY</span><br />
                      {'>'} Memory Database: <span className="text-emerald-500">CONNECTED</span><br />
                      {'>'} LLM Layers (L1/L2/L3): <span className="text-emerald-500">STANDBY</span>
                    </p>
                    <p className="text-[10px] text-gray-600">Enter a command or start a conversation below...</p>
                  </div>
                </motion.div>
              ) : (
                chatLog.map((msg, index) => (
                  <motion.div key={msg.id}
                    initial={{ opacity: 0, y: 16, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.96 }}
                    transition={{ duration: 0.18, delay: index * 0.03 }}
                    className={cn("flex", msg.role === 'user' ? 'justify-end' : 'justify-start')}>
                    <div className={cn("max-w-[80%] p-4 rounded-xl shadow-lg font-mono text-xs border",
                      msg.role === 'user'
                        ? 'glass-bubble-user text-green-100'
                        : 'glass-bubble-aura text-green-300')}>
                      <div className="flex items-center justify-between mb-2 text-[9px] text-gray-500 border-b border-white/[0.04] pb-1">
                        <span className="font-bold tracking-wider">{msg.role === 'user' ? 'USER' : 'AURA'}</span>
                        <div className="flex items-center gap-2">
                          {msg.cognitive_layer && <span className="text-blue-400">{msg.cognitive_layer}</span>}
                          <span>{new Date(msg.timestamp).toLocaleTimeString()}</span>
                        </div>
                      </div>
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                      {(msg.confidence || msg.tokens) && (
                        <div className="flex items-center gap-3 mt-2 pt-2 border-t border-white/[0.04] text-[8px] text-gray-600">
                          {msg.confidence && <span>CONF: {(msg.confidence * 100).toFixed(0)}%</span>}
                          {msg.tokens && <span>TOKENS: {msg.tokens}</span>}
                        </div>
                      )}
                    </div>
                  </motion.div>
                ))
              )}
            </AnimatePresence>
          </div>

          {/* Input Area — Liquid Glass */}
          <div className="p-4 border-t border-white/[0.05]" style={{ background: 'rgba(18,18,22,0.5)', backdropFilter: 'blur(16px) saturate(180%)', WebkitBackdropFilter: 'blur(16px) saturate(180%)' }}>
            <div className="flex gap-2">
              <textarea
                value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyPress}
                rows={2}
                className="flex-1 glass-input font-mono text-xs resize-none"
                placeholder="Enter command or dialogue... (Shift+Enter for new line)"
              />
              <button onClick={handleSend} disabled={!input.trim()}
                className={cn("px-5 py-2 rounded-xl border transition-all font-mono font-bold flex items-center",
                  input.trim()
                    ? "bg-amber-500/10 border-amber-500/25 text-amber-400 hover:bg-amber-500/20 hover:shadow-lg hover:shadow-amber-500/10"
                    : "bg-white/[0.02] text-gray-600 border-white/[0.04] cursor-not-allowed")}>
                <Send size={16} />
              </button>
            </div>
            <div className="flex items-center justify-between mt-2 text-[9px] font-mono text-gray-500">
              <span>CURRENT_LAYER: <span className="text-emerald-400">{status.cognitive.layer}</span></span>
              <span>MODEL: <span className="text-emerald-400">{status.cognitive.model.split('/')[1] || status.cognitive.model}</span></span>
              {status.cognitive.latency_ms > 0 && <span>LAST_LATENCY: <span className="text-amber-400">{status.cognitive.latency_ms}ms</span></span>}
            </div>
          </div>
        </motion.div>
      </div>

      {/* Global Scrollbar Styles */}
      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: #00000060; border-radius: 3px; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #16653480; border-radius: 3px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #166534; }
      `}</style>
    </main>
  );
}

export default function MissionControl() {
  return (
    <SettingsProvider>
      <MissionControlContent />
    </SettingsProvider>
  );
}
