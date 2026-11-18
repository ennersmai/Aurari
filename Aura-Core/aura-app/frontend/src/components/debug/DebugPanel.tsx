"use client";

import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Brain, Activity, Database, Sparkles, RefreshCw, Eye, Target } from 'lucide-react';
import { auraApi } from '@/services/auraApiService';
import { API_BASE_URL } from '@/config';
import { useSettings } from '@/contexts/SettingsContext';
import type { EmotionState, Memory, Goal } from '@/types/aura';

interface LatentState {
  status?: string;
  user_id?: string;
  version?: number;
  total_experiences_absorbed?: number;
  avg_surprise?: number;
  surprise_variance?: number;
  adaptive_threshold?: number;
  momentum_magnitude?: number;
  emotional_centroid?: Record<string, number>;
  domain_distribution?: Record<string, number>;
  summary?: string | null;
  last_updated?: string;
  updates_since_summary?: number;
}

interface AuraInternals {
  emotion: EmotionState | null;
  memoryCount: number;
  recentMemories: Memory[];
  activeGoals: Goal[];
  latentState: LatentState | null;
  systemStatus: {
    online: boolean;
    dbConnected: boolean;
    emotionEngineActive: boolean;
    learningEngineActive: boolean;
    uptime?: string;
  };
  isLoading: boolean;
}

export interface DebugPanelProps {
  conversationId?: string;
}

export default function DebugPanel({ conversationId }: DebugPanelProps) {
  const { settings } = useSettings();
  const [internals, setInternals] = useState<AuraInternals>({
    emotion: null,
    memoryCount: 0,
    recentMemories: [],
    activeGoals: [],
    latentState: null,
    systemStatus: {
      online: false,
      dbConnected: false,
      emotionEngineActive: false,
      learningEngineActive: false,
    },
    isLoading: true,
  });

  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchInternals = useCallback(async () => {
    setInternals(prev => ({ ...prev, isLoading: true }));
    try {
      const user_id = settings.commanderIdentity || 'default';
      const [status, emotion, memories, goals, latentRes] = await Promise.all([
        auraApi.getSystemStatus(),
        auraApi.getEmotionState(),
        auraApi.getRecentMemories(50, user_id),
        auraApi.getActiveGoals(),
        fetch(`${API_BASE_URL}/v1/cognition/latent-state?user_id=${encodeURIComponent(user_id)}`)
          .then(r => r.ok ? r.json() : null)
          .catch(() => null),
      ]);
      setInternals({
        emotion,
        memoryCount: memories.length,
        recentMemories: memories,
        activeGoals: goals,
        latentState: latentRes?.latent_state || null,
        systemStatus: {
          online: status.healthy,
          dbConnected: status.database,
          emotionEngineActive: true,
          learningEngineActive: true,
        },
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch Aura internals:', error);
      setInternals(prev => ({ ...prev, isLoading: false }));
    }
  }, [settings.commanderIdentity]);

  useEffect(() => {
    fetchInternals();
  }, [conversationId, fetchInternals]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchInternals, 30000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchInternals]);

  return (
    <div className="w-full h-full overflow-auto p-4 space-y-3 glass-scrollbar" style={{ background: 'transparent' }}>
      {/* Header */}
      <div className="flex justify-between items-center pb-2 mb-1">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-emerald-400" />
          <h2 className="text-xs font-mono font-bold tracking-wider text-emerald-400/90">AURA_INTERNALS</h2>
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-2 py-1 text-[10px] font-mono rounded-md border transition-all ${
              autoRefresh
                ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
                : 'glass-chip text-gray-500'
            }`}
          >
            AUTO: {autoRefresh ? 'ON' : 'OFF'}
          </button>
          <button
            onClick={fetchInternals}
            disabled={internals.isLoading}
            className="glass-btn-icon w-7 h-7"
          >
            <RefreshCw size={11} className={internals.isLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* System Status — Liquid Glass Panel */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-panel-sm p-3"
      >
        <div className="flex items-center gap-2 mb-2.5">
          <Activity size={13} className="text-emerald-400" />
          <h3 className="text-[11px] font-mono font-bold tracking-wider text-emerald-400/90">SYSTEM_STATUS</h3>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[10px] font-mono">
          <StatusItem label="ONLINE" value={internals.systemStatus.online} />
          <StatusItem label="DATABASE" value={internals.systemStatus.dbConnected} />
          <StatusItem label="EMOTION_ENGINE" value={internals.systemStatus.emotionEngineActive} />
          <StatusItem label="LEARNING_ENGINE" value={internals.systemStatus.learningEngineActive} />
        </div>
        {internals.systemStatus.uptime && (
          <div className="mt-2 text-[9px] text-gray-500 font-mono">
            UPTIME: {internals.systemStatus.uptime}
          </div>
        )}
      </motion.div>

      {/* Emotion State — Liquid Glass Panel */}
      {internals.emotion && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="glass-panel-sm p-3"
        >
          <div className="flex items-center gap-2 mb-2.5">
            <Sparkles size={13} className="text-violet-400" />
            <h3 className="text-[11px] font-mono font-bold tracking-wider text-violet-400/90">EMOTION_VECTOR</h3>
          </div>
          <div className="space-y-2">
          {/* Emotion bubble — flex-wrap so long translator phrases don't overflow */}
          <div className="text-[10px] font-mono flex items-start gap-2 flex-wrap">
            <span className="text-gray-500 shrink-0 pt-0.5">DOMINANT:</span>
            <span
              className="glass-chip glass-chip-active px-2 py-0.5 min-w-0 flex-1 break-words whitespace-normal leading-snug"
              style={{ fontSize: 'clamp(8px, 0.62rem, 10px)' }}
            >
              {internals.emotion.current_state}
            </span>
          </div>
            <div className="space-y-1 max-h-80 overflow-y-auto glass-scrollbar">
              <div className="text-[8px] text-gray-500 font-mono mb-1 tracking-wider">PRIMARY (9)</div>
              <div className="grid grid-cols-3 gap-1.5 text-[9px] font-mono">
                <EmotionBar label="LOVE" value={internals.emotion.love || 0} />
                <EmotionBar label="JOY" value={internals.emotion.joy} />
                <EmotionBar label="INTEREST" value={internals.emotion.interest || 0} />
                <EmotionBar label="TRUST" value={internals.emotion.trust} />
                <EmotionBar label="FEAR" value={internals.emotion.fear} />
                <EmotionBar label="SADNESS" value={internals.emotion.sadness} />
                <EmotionBar label="ANGER" value={internals.emotion.anger} />
                <EmotionBar label="SURPRISE" value={internals.emotion.surprise} />
                <EmotionBar label="DISGUST" value={internals.emotion.disgust} />
              </div>
              <div className="text-[8px] text-gray-500 font-mono mt-2 mb-1 tracking-wider">AESTHETIC (6)</div>
              <div className="grid grid-cols-3 gap-1.5 text-[9px] font-mono">
                <EmotionBar label="AWE" value={internals.emotion.awe || 0} />
                <EmotionBar label="BEAUTY" value={internals.emotion.beauty || 0} />
                <EmotionBar label="WONDER" value={internals.emotion.wonder || 0} />
                <EmotionBar label="SERENITY" value={internals.emotion.serenity || 0} />
                <EmotionBar label="MELANCHOLY" value={internals.emotion.melancholy || 0} />
                <EmotionBar label="NOSTALGIA" value={internals.emotion.nostalgia || 0} />
              </div>
              <div className="text-[8px] text-gray-500 font-mono mt-2 mb-1 tracking-wider">SOCIAL (6)</div>
              <div className="grid grid-cols-3 gap-1.5 text-[9px] font-mono">
                <EmotionBar label="EMPATHY" value={internals.emotion.empathy || 0} />
                <EmotionBar label="GRATITUDE" value={internals.emotion.gratitude || 0} />
                <EmotionBar label="PRIDE" value={internals.emotion.pride || 0} />
                <EmotionBar label="SHAME" value={internals.emotion.shame || 0} />
                <EmotionBar label="ENVY" value={internals.emotion.envy || 0} />
                <EmotionBar label="COMPASSION" value={internals.emotion.compassion || 0} />
              </div>
              <div className="text-[8px] text-gray-500 font-mono mt-2 mb-1 tracking-wider">COGNITIVE (6)</div>
              <div className="grid grid-cols-3 gap-1.5 text-[9px] font-mono">
                <EmotionBar label="CURIOSITY" value={internals.emotion.curiosity || 0} />
                <EmotionBar label="CONFUSION" value={internals.emotion.confusion || 0} />
                <EmotionBar label="CERTAINTY" value={internals.emotion.certainty || 0} />
                <EmotionBar label="DOUBT" value={internals.emotion.doubt || 0} />
                <EmotionBar label="FASCINATION" value={internals.emotion.fascination || 0} />
                <EmotionBar label="BOREDOM" value={internals.emotion.boredom || 0} />
              </div>
            </div>
            <div className="text-[9px] text-gray-500 font-mono mt-1">
              ENTROPY: <span className="text-violet-300">{internals.emotion.entropy.toFixed(3)}</span>
            </div>
          </div>
        </motion.div>
      )}

      {/* TITANS Latent Memory — Liquid Glass Panel */}
      {internals.latentState && internals.latentState.status !== 'no_state' && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.08 }}
          className="glass-panel-sm p-3"
        >
          <div className="flex items-center gap-2 mb-2.5">
            <Brain size={13} className="text-cyan-400" />
            <h3 className="text-[11px] font-mono font-bold tracking-wider text-cyan-400/90">LATENT_INTUITION</h3>
            <span className="ml-auto text-[8px] font-mono text-cyan-600">TITANS v{internals.latentState.version || 0}</span>
          </div>
          
          {/* Summary */}
          {internals.latentState.summary && (
            <div className="text-[9px] font-mono text-cyan-200/80 p-2 rounded-lg mb-2 leading-relaxed italic"
              style={{ background: 'rgba(6,182,212,0.06)', border: '1px solid rgba(6,182,212,0.12)' }}>
              {internals.latentState.summary}
            </div>
          )}

          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[9px] font-mono">
            <div>
              <span className="text-gray-500">ABSORBED:</span>{' '}
              <span className="text-cyan-300">{internals.latentState.total_experiences_absorbed || 0}</span>
            </div>
            <div>
              <span className="text-gray-500">SURPRISE_μ:</span>{' '}
              <span className="text-cyan-300">{(internals.latentState.avg_surprise || 0).toFixed(3)}</span>
            </div>
            <div>
              <span className="text-gray-500">THRESHOLD:</span>{' '}
              <span className="text-cyan-300">{(internals.latentState.adaptive_threshold || 0).toFixed(3)}</span>
            </div>
            <div>
              <span className="text-gray-500">MOMENTUM:</span>{' '}
              <span className="text-cyan-300">{(internals.latentState.momentum_magnitude || 0).toFixed(3)}</span>
            </div>
          </div>

          {/* Emotional Centroid */}
          {internals.latentState.emotional_centroid && Object.keys(internals.latentState.emotional_centroid).length > 0 && (
            <div className="mt-2">
              <div className="text-[8px] text-gray-500 font-mono mb-1">EMOTIONAL_CENTROID:</div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(internals.latentState.emotional_centroid).slice(0, 5).map(([k, v]) => (
                  <span key={k} className="text-[8px] font-mono px-1.5 py-0.5 rounded"
                    style={{ background: 'rgba(6,182,212,0.1)', border: '1px solid rgba(6,182,212,0.15)', color: 'rgba(6,182,212,0.9)' }}>
                    {k}:{(v as number).toFixed(2)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Domain Distribution */}
          {internals.latentState.domain_distribution && Object.keys(internals.latentState.domain_distribution).length > 0 && (
            <div className="mt-2">
              <div className="text-[8px] text-gray-500 font-mono mb-1">DOMAIN_AFFINITY:</div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(internals.latentState.domain_distribution).slice(0, 4).map(([k, v]) => (
                  <span key={k} className="text-[8px] font-mono px-1.5 py-0.5 rounded"
                    style={{ background: 'rgba(56,189,248,0.06)', border: '1px solid rgba(56,189,248,0.12)', color: 'rgba(56,189,248,0.8)' }}>
                    {k}:{((v as number) * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      )}

      {/* Memory System — Liquid Glass Panel (Enriched) */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass-panel-sm p-3"
      >
        <div className="flex items-center gap-2 mb-2.5">
          <Database size={13} className="text-sky-400" />
          <h3 className="text-[11px] font-mono font-bold tracking-wider text-sky-400/90">HIPPOCAMPUS</h3>
        </div>
        <div className="text-[10px] font-mono mb-2">
          <span className="text-gray-500">TOTAL_MEMORIES:</span>{' '}
          <span className="text-sky-300 font-bold">{internals.memoryCount}</span>
        </div>
        {internals.recentMemories.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[9px] text-gray-500 font-mono mb-1">RECENT_ACCESS:</div>
            {internals.recentMemories.slice(0, 5).map((memory, i) => (
              <div
                key={memory.memory_id || i}
                className="text-[9px] font-mono p-2 rounded-lg"
                style={{
                  background: memory.core_memory
                    ? 'rgba(251,191,36,0.06)'
                    : 'rgba(255,255,255,0.03)',
                  border: memory.core_memory
                    ? '1px solid rgba(251,191,36,0.2)'
                    : '1px solid rgba(255,255,255,0.04)'
                }}
              >
                {/* Header: badges + importance */}
                <div className="flex items-center gap-1 mb-1">
                  {memory.core_memory && (
                    <span className="text-[7px] px-1 py-0.5 rounded font-bold"
                      style={{ background: 'rgba(251,191,36,0.15)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.3)' }}>
                      CORE
                    </span>
                  )}
                  {memory.memory_type === 'semantic' && (
                    <span className="text-[7px] px-1 py-0.5 rounded"
                      style={{ background: 'rgba(168,85,247,0.1)', color: '#c084fc', border: '1px solid rgba(168,85,247,0.2)' }}>
                      SEMANTIC
                    </span>
                  )}
                  <span className="ml-auto text-[8px] text-gray-600">
                    ⚡{((memory.importance || 0) * 100).toFixed(0)}%
                  </span>
                </div>
                {/* Content */}
                <div className="text-gray-400 leading-snug">
                  {memory.content.substring(0, 80)}{memory.content.length > 80 ? '...' : ''}
                </div>
                {/* Emotional context */}
                {memory.emotional_signature && Object.keys(memory.emotional_signature).length > 0 && (
                  <div className="mt-1 flex gap-1 flex-wrap">
                    {Object.entries(memory.emotional_signature)
                      .filter(([, v]) => (v as number) > 0.2)
                      .slice(0, 3)
                      .map(([k, v]) => (
                        <span key={k} className="text-[7px] text-violet-400/70">
                          {k}:{(v as number).toFixed(1)}
                        </span>
                      ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </motion.div>

      {/* Learning Engine — Liquid Glass Panel */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="glass-panel-sm p-3"
      >
        <div className="flex items-center gap-2 mb-2.5">
          <Brain size={13} className="text-amber-400" />
          <h3 className="text-[11px] font-mono font-bold tracking-wider text-amber-400/90">LEARNING_ENGINE</h3>
        </div>
        <div className="text-[10px] font-mono space-y-1">
          <div>
            <span className="text-gray-500">STATUS:</span>{' '}
            <span className="text-amber-300">
              {internals.systemStatus.learningEngineActive ? 'ACTIVE' : 'IDLE'}
            </span>
          </div>
          <div>
            <span className="text-gray-500">MODE:</span>{' '}
            <span className="text-amber-300/70">EXPERIENCE_CAPTURE</span>
          </div>
          <div className="text-[8px] text-gray-500 mt-1.5">
            Continuously extracting patterns from interactions...
          </div>
        </div>
      </motion.div>

      {/* Goal Engine — Liquid Glass Panel */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="glass-panel-sm p-3"
      >
        <div className="flex items-center gap-2 mb-2.5">
          <Target size={13} className="text-violet-400" />
          <h3 className="text-[11px] font-mono font-bold tracking-wider text-violet-400/90">GOAL_ENGINE</h3>
        </div>
        <div className="text-[10px] font-mono space-y-1">
          <div>
            <span className="text-gray-500">ACTIVE_GOALS:</span>{' '}
            <span className="text-violet-300 font-bold">{internals.activeGoals.length}</span>
          </div>
          {internals.activeGoals.length > 0 && (
            <div className="space-y-1.5 mt-2 max-h-32 overflow-y-auto glass-scrollbar">
              {internals.activeGoals.slice(0, 3).map((goal, i) => (
                <div
                  key={goal.goal_id || i}
                  className="text-[9px] font-mono text-violet-300/80 p-2 rounded-lg"
                  style={{ background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.12)' }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-bold truncate">{goal.name}</span>
                    <span className="text-violet-500 ml-2 shrink-0">{(goal.priority * 100).toFixed(0)}%</span>
                  </div>
                  <div className="text-gray-400 text-[8px] truncate">
                    {goal.description.substring(0, 50)}...
                  </div>
                  <div className="text-gray-500 text-[7px] mt-1">
                    {goal.goal_type} · {Math.round(goal.progress * 100)}% complete
                  </div>
                </div>
              ))}
            </div>
          )}
          {internals.activeGoals.length === 0 && (
            <div className="text-[9px] text-gray-500 mt-2">
              No active goals. Waiting for goal generation...
            </div>
          )}
        </div>
      </motion.div>

      {/* Session Info */}
      {conversationId && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.25 }}
          className="glass-panel-sm p-3"
        >
          <div className="flex items-center gap-2 mb-2">
            <Eye size={13} className="text-gray-400" />
            <h3 className="text-[11px] font-mono font-bold tracking-wider text-gray-400/90">SESSION_INFO</h3>
          </div>
          <div className="text-[9px] font-mono text-gray-500 break-all">
            CONVERSATION_ID: {conversationId}
          </div>
        </motion.div>
      )}

      {/* Footer */}
      <div className="text-[8px] text-gray-600 font-mono text-center pt-2 border-t border-white/[0.04]">
        AURA_DEBUG_PANEL · REAL-TIME_MONITORING
      </div>
    </div>
  );
}

// Helper Components
function StatusItem({ label, value }: { label: string; value: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-gray-500">{label}:</span>
      <span className={value ? 'text-emerald-400' : 'text-red-400'}>
        {value ? '✓ OK' : '✗ OFFLINE'}
      </span>
    </div>
  );
}

function EmotionBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-gray-500 mb-0.5">{label}</div>
      <div className="w-full bg-white/[0.05] h-1 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${value * 100}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
          className="h-full rounded-full"
          style={{
            background: 'linear-gradient(90deg, rgba(139,92,246,0.6), rgba(139,92,246,0.9))',
            boxShadow: '0 0 6px rgba(139,92,246,0.3)',
          }}
        />
      </div>
      <div className="text-gray-600 mt-0.5 text-[8px]">{(value * 100).toFixed(0)}%</div>
    </div>
  );
}
