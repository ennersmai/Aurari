"use client";

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Cpu, Cloud, ChevronDown, ChevronUp, RefreshCw, Download,
  Zap, Brain, MessageSquare, Heart, FileJson, CheckCircle2,
  XCircle, Loader2, Monitor, Globe, ArrowLeftRight, Mic
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { API_BASE_URL } from '@/config';

// ============================================================================
// TYPES
// ============================================================================

interface OllamaModel {
  name: string;
  size?: number;
  digest?: string;
  modified_at?: string;
  details?: {
    family?: string;
    parameter_size?: string;
    quantization_level?: string;
  };
}

interface LayerConfig {
  model: string;
  provider: 'local' | 'cloud';
  role: string;
}

interface AIProviderStatus {
  ollama_available: boolean;
  ollama_url: string;
  ollama_models: OllamaModel[];
  qwen3_tts_available: boolean;
  qwen3_tts_url: string;
  fishaudio_available: boolean;
  fishaudio_url: string;
  tts_provider: string;
  local_llm_enabled: boolean;
  fallback_to_cloud: boolean;
  layers: Record<string, LayerConfig>;
}

// ============================================================================
// LAYER METADATA
// ============================================================================

const LAYER_META: Record<string, { icon: React.ReactNode; color: string; bgColor: string; borderColor: string }> = {
  l1: {
    icon: <Zap size={14} />,
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-900/20',
    borderColor: 'border-yellow-900/50',
  },
  l2: {
    icon: <Brain size={14} />,
    color: 'text-blue-400',
    bgColor: 'bg-blue-900/20',
    borderColor: 'border-blue-900/50',
  },
  l3: {
    icon: <MessageSquare size={14} />,
    color: 'text-green-400',
    bgColor: 'bg-green-900/20',
    borderColor: 'border-green-900/50',
  },
  l4: {
    icon: <Heart size={14} />,
    color: 'text-pink-400',
    bgColor: 'bg-pink-900/20',
    borderColor: 'border-pink-900/50',
  },
  l5: {
    icon: <FileJson size={14} />,
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-900/20',
    borderColor: 'border-cyan-900/50',
  },
};

// Popular local models for quick selection
const SUGGESTED_LOCAL_MODELS = [
  { name: 'llama3.2', desc: 'Meta Llama 3.2 3B', size: '2GB', multimodal: false },
  { name: 'llama3.2:11b', desc: 'Llama 3.2 11B Vision', size: '6.4GB', multimodal: true },
  { name: 'qwen2.5:14b', desc: 'Qwen 2.5 14B', size: '8.9GB', multimodal: false },
  { name: 'qwen2.5:7b', desc: 'Qwen 2.5 7B', size: '4.4GB', multimodal: false },
  { name: 'mistral', desc: 'Mistral 7B', size: '4.1GB', multimodal: false },
  { name: 'gemma2:9b', desc: 'Google Gemma 2 9B', size: '5.4GB', multimodal: false },
  { name: 'llava:13b', desc: 'LLaVA 13B Vision', size: '8GB', multimodal: true },
  { name: 'deepseek-r1:14b', desc: 'DeepSeek R1 14B', size: '9GB', multimodal: false },
];

// ============================================================================
// COMPONENT
// ============================================================================

export default function AIProviderPanel() {
  const [isExpanded, setIsExpanded] = useState(false);
  const [status, setStatus] = useState<AIProviderStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [pullingModel, setPullingModel] = useState<string | null>(null);
  const [editingLayer, setEditingLayer] = useState<string | null>(null);
  const [customModel, setCustomModel] = useState('');
  const [switchSuccess, setSwitchSuccess] = useState<string | null>(null);

  // Fetch AI provider status
  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE_URL}/local-ai/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch AI provider status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isExpanded) {
      fetchStatus();
    }
  }, [isExpanded, fetchStatus]);

  // Pull a model
  const handlePullModel = async (modelName: string) => {
    setPullingModel(modelName);
    try {
      const res = await fetch(`${API_BASE_URL}/local-ai/ollama/pull`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_name: modelName }),
      });
      if (res.ok) {
        await fetchStatus(); // Refresh model list
      }
    } catch (err) {
      console.error('Failed to pull model:', err);
    } finally {
      setPullingModel(null);
    }
  };

  // Switch a layer's model
  const handleSwitchLayer = async (layer: string, provider: 'local' | 'cloud', model: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}/local-ai/layer/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layer, provider, model }),
      });
      if (res.ok) {
        setSwitchSuccess(layer);
        setTimeout(() => setSwitchSuccess(null), 2000);
        await fetchStatus();
      }
    } catch (err) {
      console.error('Failed to switch layer:', err);
    }
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return '?';
    const gb = bytes / (1024 * 1024 * 1024);
    return gb >= 1 ? `${gb.toFixed(1)}GB` : `${(bytes / (1024 * 1024)).toFixed(0)}MB`;
  };

  const localModelNames = status?.ollama_models?.map(m => m.name) || [];

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full bg-black/40 border border-cyan-900/50 rounded-lg backdrop-blur-sm overflow-hidden"
    >
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-cyan-900/10 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="relative">
            <Cpu size={16} className="text-cyan-400" />
            {status?.ollama_available && (
              <div className="absolute -top-1 -right-1 w-2 h-2 bg-green-500 rounded-full animate-pulse" />
            )}
          </div>
          <span className="font-mono text-sm text-cyan-400">AI_PROVIDER_CONTROL</span>
          
          {/* Quick status badges */}
          <div className="flex items-center gap-2 ml-2">
            {status && (
              <>
                <span className={cn(
                  "text-[9px] font-mono px-2 py-0.5 rounded border",
                  status.ollama_available
                    ? "bg-green-900/30 border-green-700/50 text-green-400"
                    : "bg-red-900/30 border-red-700/50 text-red-400"
                )}>
                  <Monitor size={8} className="inline mr-1" />
                  {status.ollama_available ? 'LOCAL' : 'NO LOCAL'}
                </span>
                <span className="text-[9px] font-mono px-2 py-0.5 rounded border bg-blue-900/30 border-blue-700/50 text-blue-400">
                  <Globe size={8} className="inline mr-1" />
                  CLOUD
                </span>
                {status.qwen3_tts_available && (
                  <span className="text-[9px] font-mono px-2 py-0.5 rounded border bg-purple-900/30 border-purple-700/50 text-purple-400">
                    <Mic size={8} className="inline mr-1" />
                    QWEN3-TTS
                  </span>
                )}
                {status.fishaudio_available && (
                  <span className="text-[9px] font-mono px-2 py-0.5 rounded border bg-orange-900/30 border-orange-700/50 text-orange-400">
                    <Mic size={8} className="inline mr-1" />
                    FISHAUDIO
                  </span>
                )}
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {loading && <Loader2 size={14} className="text-cyan-400 animate-spin" />}
          {isExpanded ? <ChevronUp size={16} className="text-cyan-400" /> : <ChevronDown size={16} className="text-cyan-400" />}
        </div>
      </button>

      {/* Expanded Panel */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="border-t border-cyan-900/50"
          >
            <div className="p-4 space-y-4">

              {/* === OLLAMA STATUS === */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Monitor size={14} className={status?.ollama_available ? 'text-green-400' : 'text-red-400'} />
                  <span className="font-mono text-xs text-gray-400">OLLAMA_ENGINE</span>
                  <span className={cn(
                    "font-mono text-[10px] px-2 py-0.5 rounded",
                    status?.ollama_available
                      ? "bg-green-900/30 text-green-400"
                      : "bg-red-900/30 text-red-400"
                  )}>
                    {status?.ollama_available ? 'ONLINE' : 'OFFLINE'}
                  </span>
                  <span className="text-[10px] text-gray-600 font-mono">{status?.ollama_url}</span>
                </div>
                <button
                  onClick={fetchStatus}
                  className="p-1.5 rounded border border-cyan-900/50 hover:bg-cyan-900/20 transition-colors"
                  title="Refresh status"
                >
                  <RefreshCw size={12} className={cn("text-cyan-400", loading && "animate-spin")} />
                </button>
              </div>

              {/* === COGNITIVE LAYER ROUTING === */}
              <div className="space-y-2">
                <div className="flex items-center gap-2 mb-3">
                  <ArrowLeftRight size={14} className="text-cyan-400" />
                  <span className="font-mono text-xs text-cyan-400">LAYER_ROUTING</span>
                  <span className="text-[9px] text-gray-500 font-mono">Click a layer to switch provider</span>
                </div>

                {status?.layers && Object.entries(status.layers).map(([layerKey, layerConfig]) => {
                  const meta = LAYER_META[layerKey];
                  const isLocal = layerConfig.provider === 'local';
                  const isEditing = editingLayer === layerKey;

                  return (
                    <motion.div
                      key={layerKey}
                      layout
                      className={cn(
                        "rounded-lg border p-3 transition-all",
                        meta.bgColor, meta.borderColor,
                        switchSuccess === layerKey && "ring-2 ring-green-500/50"
                      )}
                    >
                      {/* Layer Header */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={meta.color}>{meta.icon}</span>
                          <span className={cn("font-mono text-xs font-bold", meta.color)}>
                            {layerKey.toUpperCase()}
                          </span>
                          <span className="text-[10px] text-gray-500 font-mono">
                            {layerConfig.role}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          {/* Provider Badge */}
                          <span className={cn(
                            "text-[9px] font-mono px-2 py-0.5 rounded border flex items-center gap-1",
                            isLocal
                              ? "bg-green-900/40 border-green-700/50 text-green-300"
                              : "bg-blue-900/40 border-blue-700/50 text-blue-300"
                          )}>
                            {isLocal ? <Monitor size={8} /> : <Cloud size={8} />}
                            {isLocal ? 'LOCAL' : 'CLOUD'}
                          </span>
                          {switchSuccess === layerKey && (
                            <CheckCircle2 size={14} className="text-green-400" />
                          )}
                          <button
                            onClick={() => setEditingLayer(isEditing ? null : layerKey)}
                            className={cn(
                              "text-[10px] font-mono px-2 py-1 rounded border transition-colors",
                              isEditing
                                ? "bg-cyan-900/30 border-cyan-700/50 text-cyan-300"
                                : "border-gray-700/50 text-gray-400 hover:bg-gray-900/30"
                            )}
                          >
                            SWITCH
                          </button>
                        </div>
                      </div>

                      {/* Current Model */}
                      <div className="mt-1.5 text-[10px] font-mono text-gray-400">
                        MODEL: <span className="text-gray-200">{layerConfig.model}</span>
                      </div>

                      {/* Edit Panel */}
                      <AnimatePresence>
                        {isEditing && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="mt-3 pt-3 border-t border-gray-800 space-y-2"
                          >
                            {/* Local Models (from Ollama) */}
                            {status?.ollama_available && localModelNames.length > 0 && (
                              <div>
                                <span className="text-[9px] font-mono text-green-400 mb-1 block">
                                  LOCAL MODELS (Ollama):
                                </span>
                                <div className="flex flex-wrap gap-1">
                                  {localModelNames.map(name => (
                                    <button
                                      key={name}
                                      onClick={() => handleSwitchLayer(layerKey, 'local', name)}
                                      className={cn(
                                        "text-[9px] font-mono px-2 py-1 rounded border transition-colors",
                                        layerConfig.model === `local/${name}`
                                          ? "bg-green-900/40 border-green-600 text-green-300"
                                          : "border-gray-700 text-gray-400 hover:bg-green-900/20 hover:text-green-300"
                                      )}
                                    >
                                      <Monitor size={8} className="inline mr-1" />
                                      {name}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Custom model input */}
                            <div className="flex gap-2">
                              <input
                                type="text"
                                value={customModel}
                                onChange={(e) => setCustomModel(e.target.value)}
                                placeholder="cloud/model-name or local-model"
                                className="flex-1 bg-black/50 border border-gray-700 rounded px-2 py-1 text-[10px] font-mono text-gray-300 placeholder-gray-600 focus:outline-none focus:border-cyan-500"
                              />
                              <button
                                onClick={() => {
                                  if (customModel.trim()) {
                                    const isLocalInput = customModel.startsWith('local/') || localModelNames.includes(customModel);
                                    const provider = isLocalInput ? 'local' : 'cloud';
                                    const model = customModel.startsWith('local/') ? customModel.slice(6) : customModel;
                                    handleSwitchLayer(layerKey, provider, model);
                                    setCustomModel('');
                                    setEditingLayer(null);
                                  }
                                }}
                                disabled={!customModel.trim()}
                                className="text-[9px] font-mono px-3 py-1 rounded border border-cyan-700/50 bg-cyan-900/20 text-cyan-300 hover:bg-cyan-900/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                              >
                                SET
                              </button>
                            </div>

                            {/* Revert to cloud */}
                            {isLocal && (
                              <button
                                onClick={() => {
                                  // Revert to original cloud model for this layer
                                  const cloudDefaults: Record<string, string> = {
                                    l1: 'mistralai/mistral-large-2512',
                                    l2: 'moonshotai/kimi-k2-0905',
                                    l3: 'x-ai/grok-4.3',
                                    l4: 'qwen/qwen-2.5-72b-instruct',
                                    l5: 'minimax/minimax-01',
                                  };
                                  handleSwitchLayer(layerKey, 'cloud', cloudDefaults[layerKey] || '');
                                  setEditingLayer(null);
                                }}
                                className="text-[9px] font-mono px-2 py-1 rounded border border-blue-700/50 bg-blue-900/20 text-blue-300 hover:bg-blue-900/40 transition-colors"
                              >
                                <Cloud size={8} className="inline mr-1" />
                                REVERT TO CLOUD
                              </button>
                            )}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </motion.div>
                  );
                })}
              </div>

              {/* === MODEL LIBRARY === */}
              {status?.ollama_available && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Download size={14} className="text-cyan-400" />
                    <span className="font-mono text-xs text-cyan-400">MODEL_LIBRARY</span>
                    <span className="text-[9px] text-gray-500 font-mono">
                      {status.ollama_models.length} models loaded
                    </span>
                  </div>

                  {/* Installed Models */}
                  {status.ollama_models.length > 0 && (
                    <div className="space-y-1">
                      {status.ollama_models.map((model) => (
                        <div
                          key={model.name}
                          className="flex items-center justify-between p-2 bg-black/30 border border-gray-800 rounded text-[10px] font-mono"
                        >
                          <div className="flex items-center gap-2">
                            <CheckCircle2 size={10} className="text-green-500" />
                            <span className="text-gray-200">{model.name}</span>
                            {model.details?.parameter_size && (
                              <span className="text-gray-500">{model.details.parameter_size}</span>
                            )}
                          </div>
                          <span className="text-gray-600">{formatSize(model.size)}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Suggested Models to Pull */}
                  <div className="mt-2">
                    <span className="text-[9px] text-gray-500 font-mono block mb-1">
                      SUGGESTED MODELS:
                    </span>
                    <div className="grid grid-cols-2 gap-1">
                      {SUGGESTED_LOCAL_MODELS.filter(
                        m => !localModelNames.some(n => n.startsWith(m.name.split(':')[0]))
                      ).slice(0, 6).map((model) => (
                        <button
                          key={model.name}
                          onClick={() => handlePullModel(model.name)}
                          disabled={pullingModel !== null}
                          className="flex items-center justify-between p-2 bg-black/20 border border-gray-800 rounded text-[9px] font-mono text-gray-400 hover:bg-cyan-900/10 hover:border-cyan-800/50 hover:text-cyan-300 transition-colors disabled:opacity-40"
                        >
                          <div className="flex items-center gap-1.5">
                            {pullingModel === model.name ? (
                              <Loader2 size={9} className="animate-spin text-cyan-400" />
                            ) : (
                              <Download size={9} />
                            )}
                            <span>{model.name}</span>
                            {model.multimodal && (
                              <span className="text-[7px] bg-purple-900/40 text-purple-300 px-1 rounded">VIS</span>
                            )}
                          </div>
                          <span className="text-gray-600">{model.size}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* === TTS STATUS === */}
              <div className="flex items-center justify-between p-2 bg-black/30 border border-gray-800 rounded">
                <div className="flex items-center gap-2">
                  <Mic size={12} className={status?.fishaudio_available || status?.qwen3_tts_available ? 'text-purple-400' : 'text-gray-500'} />
                  <span className="font-mono text-[10px] text-gray-400">TTS_ENGINE:</span>
                  <span className={cn(
                    "font-mono text-[10px]",
                    status?.tts_provider === 'fishaudio' ? 'text-orange-300' : status?.tts_provider === 'qwen3' ? 'text-purple-300' : 'text-blue-300'
                  )}>
                    {status?.tts_provider === 'fishaudio' ? 'FishAudio (Local)' : status?.tts_provider === 'qwen3' ? 'Qwen3-TTS (Local)' : 'Edge-TTS (Cloud)'}
                  </span>
                </div>
                {status?.fishaudio_available && (
                  <span className="text-[9px] font-mono text-green-400">FISHAUDIO READY</span>
                )}
                {status?.qwen3_tts_available && (
                  <span className="text-[9px] font-mono text-green-400">QWEN3 READY</span>
                )}
                {!status?.fishaudio_available && status?.tts_provider === 'fishaudio' && (
                  <span className="text-[9px] font-mono text-red-400">FISHAUDIO NOT CONNECTED</span>
                )}
                {!status?.qwen3_tts_available && status?.tts_provider === 'qwen3' && (
                  <span className="text-[9px] font-mono text-red-400">QWEN3 NOT CONNECTED</span>
                )}
              </div>

              {/* === OLLAMA NOT RUNNING HELP === */}
              {status && !status.ollama_available && (
                <div className="p-3 bg-yellow-900/10 border border-yellow-900/30 rounded text-[10px] font-mono text-yellow-300/80 space-y-1">
                  <div className="flex items-center gap-2 mb-1">
                    <XCircle size={12} className="text-yellow-500" />
                    <span className="text-yellow-400 font-bold">OLLAMA NOT DETECTED</span>
                  </div>
                  <div>Install: <span className="text-yellow-200">https://ollama.com/download</span></div>
                  <div>Start: <span className="text-yellow-200">ollama serve</span></div>
                  <div>Pull a model: <span className="text-yellow-200">ollama pull llama3.2</span></div>
                </div>
              )}

            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
