import React, { useState, useEffect, useCallback } from 'react';
import { Brain, Activity, History, Trash2, RefreshCw, AlertCircle, Terminal } from 'lucide-react';
import { cn } from '@/lib/utils';
import EmotionRadar from '@/components/emotion/EmotionRadar';
import MemoryStream from '@/components/memory/MemoryStream';
import SystemConsole from '@/components/system/SystemConsole';
import type { EmotionState, Memory, Insight } from '@/types/aura';
import { API_BASE_URL } from '@/config';

interface NeuralSidebarProps {
  emotion: EmotionState;
  memories: Memory[];
  onRefreshMemories?: () => void;
}

type TabType = 'emotion' | 'cortex' | 'episodic' | 'logs';

const tabColors: Record<string, { active: string; bg: string; border: string; muted: string }> = {
  green:  { active: '#4ade80', bg: 'rgba(74,222,128,0.1)',   border: '#4ade80', muted: 'rgba(74,222,128,0.25)' },
  blue:   { active: '#60a5fa', bg: 'rgba(59,130,246,0.1)',   border: '#60a5fa', muted: 'rgba(59,130,246,0.25)' },
  purple: { active: '#c084fc', bg: 'rgba(168,85,247,0.1)',   border: '#c084fc', muted: 'rgba(168,85,247,0.25)' },
  slate:  { active: '#94a3b8', bg: 'rgba(148,163,184,0.1)',  border: '#94a3b8', muted: 'rgba(148,163,184,0.25)' },
};

export default function NeuralSidebar({ emotion, memories, onRefreshMemories }: NeuralSidebarProps) {
  const [activeTab, setActiveTab] = useState<TabType>('emotion');
  const [insights, setInsights] = useState<Insight[]>([]);
  const [isLoadingInsights, setIsLoadingInsights] = useState(false);
  const [insightsError, setInsightsError] = useState<string | null>(null);

  const fetchInsights = useCallback(async () => {
    setIsLoadingInsights(true);
    setInsightsError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/learning/insights?limit=50`);
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      const data = await response.json();
      if (data.success && Array.isArray(data.insights)) {
        setInsights(data.insights);
      } else {
        throw new Error('Invalid response format');
      }
    } catch (error) {
      console.error('Failed to fetch insights:', error);
      setInsightsError(error instanceof Error ? error.message : 'Failed to load insights');
    } finally {
      setIsLoadingInsights(false);
    }
  }, []);

  const deleteInsight = useCallback(async (insightId: string) => {
    try {
      await fetch(`${API_BASE_URL}/learning/insights/${insightId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
      });
    } catch (error) {
      console.warn('Delete endpoint may not be available, removing from UI only:', error);
    }
    setInsights(prev => prev.filter(i => i.insight_id !== insightId));
  }, []);

  useEffect(() => {
    if (activeTab === 'cortex' && insights.length === 0) {
      fetchInsights();
    }
    let intervalId: NodeJS.Timeout | null = null;
    if (activeTab === 'cortex') {
      intervalId = setInterval(() => { fetchInsights(); }, 30000);
    }
    return () => { if (intervalId) clearInterval(intervalId); };
  }, [activeTab, fetchInsights, insights.length]);

  const tabs = [
    { id: 'emotion' as TabType, label: 'EMOTION', icon: Activity, color: 'green' },
    { id: 'cortex' as TabType, label: 'CORTEX', icon: Brain, color: 'blue' },
    { id: 'episodic' as TabType, label: 'EPISODIC', icon: History, color: 'purple' },
    { id: 'logs' as TabType, label: 'LOGS', icon: Terminal, color: 'slate' },
  ];

  return (
    <div className="h-full flex flex-col" style={{
      background: 'rgba(14, 14, 18, 0.92)',
      border: '1px solid rgba(255,255,255,0.06)',
      borderRadius: '16px',
      overflow: 'hidden',
      borderColor: 'rgba(74,222,128,0.1)',
    }}>
      {/* Tab Navigation */}
      <div className="flex shrink-0" style={{
        background: 'rgba(18, 18, 22, 0.5)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          const c = tabColors[tab.color];
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`glass-tab ${isActive ? 'glass-tab-active' : ''}`}
              style={isActive ? {
                borderBottomColor: c.border,
                color: c.active,
                background: c.bg,
              } : undefined}
            >
              <Icon size={13} />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto glass-scrollbar">
        {activeTab === 'emotion' && (
          <div className="p-4">
            <EmotionRadar data={emotion} showPhysics={true} />
          </div>
        )}

        {activeTab === 'cortex' && (
          <div className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Brain size={14} className="text-blue-400" />
                  <h3 className="text-xs font-mono font-bold tracking-wider text-blue-400/90">LEARNED INSIGHTS</h3>
                </div>
                <button
                  onClick={fetchInsights}
                  disabled={isLoadingInsights}
                  className="glass-btn-icon w-7 h-7"
                >
                  <RefreshCw size={11} className={cn("text-blue-400", isLoadingInsights && "animate-spin")} />
                </button>
              </div>

              {isLoadingInsights && (
                <div className="flex items-center justify-center py-8">
                  <div className="text-center space-y-2">
                    <RefreshCw size={22} className="mx-auto text-blue-400 animate-spin" />
                    <p className="text-[10px] font-mono text-gray-500">Loading insights...</p>
                  </div>
                </div>
              )}

              {insightsError && !isLoadingInsights && (
                <div className="flex items-center gap-2 p-3 rounded-lg text-[10px] font-mono text-red-400"
                  style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
                  <AlertCircle size={12} />
                  <span>{insightsError}</span>
                </div>
              )}

              {!isLoadingInsights && !insightsError && insights.length > 0 && (
                <div className="space-y-2">
                  <div className="text-[9px] font-mono text-gray-500">
                    COUNT: <span className="text-blue-400">{insights.length}</span>
                  </div>
                  {insights.map((insight) => (
                    <div
                      key={insight.insight_id}
                      className="group p-3 rounded-lg transition-colors"
                      style={{
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid',
                        borderColor:
                          insight.type === 'FACT' ? 'rgba(59,130,246,0.2)' :
                          insight.type === 'PREFERENCE' ? 'rgba(168,85,247,0.2)' :
                          'rgba(251,146,60,0.2)'
                      }}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span
                          className="text-[9px] font-mono font-bold px-2 py-0.5 rounded-md"
                          style={{
                            backgroundColor:
                              insight.type === 'FACT' ? 'rgba(59,130,246,0.15)' :
                              insight.type === 'PREFERENCE' ? 'rgba(168,85,247,0.15)' :
                              'rgba(251,146,60,0.15)',
                            color:
                              insight.type === 'FACT' ? '#60a5fa' :
                              insight.type === 'PREFERENCE' ? '#c084fc' :
                              '#fb923c'
                          }}
                        >
                          {insight.type}
                        </span>
                        <button
                          onClick={() => {
                            const contentStr = typeof insight.content === 'string' ? insight.content : JSON.stringify(insight.content);
                            if (confirm(`Delete this insight?\n\n"${contentStr}"`)) {
                              deleteInsight(insight.insight_id);
                            }
                          }}
                          className="glass-btn-icon w-6 h-6 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <Trash2 size={11} className="text-red-400" />
                        </button>
                      </div>
                      <p className="text-[10px] font-mono text-gray-300 break-words whitespace-pre-wrap">
                        {typeof insight.content === 'string' ? insight.content : JSON.stringify(insight.content)}
                      </p>
                      <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/[0.04] text-[8px] font-mono text-gray-600">
                        <span>CONF: <span className="text-emerald-400/80">{(insight.confidence * 100).toFixed(0)}%</span></span>
                        <span>USED: <span className="text-gray-400">{insight.application_count || 0}x</span></span>
                        {insight.domain && <span className="text-gray-500">{insight.domain}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {!isLoadingInsights && !insightsError && insights.length === 0 && (
                <div className="flex items-center justify-center py-8">
                  <div className="text-center space-y-2">
                    <Brain size={28} className="mx-auto text-blue-800" />
                    <p className="text-[10px] font-mono text-gray-500">No insights learned yet</p>
                    <p className="text-[8px] font-mono text-gray-600">
                      Aura will extract insights after analyzing interactions
                    </p>
                  </div>
                </div>
              )}
          </div>
        )}

        {activeTab === 'episodic' && (
          <div className="h-full flex flex-col">
            <div className="flex items-center justify-between mb-3 px-4 pt-4">
              <div className="flex items-center gap-2">
                <History size={14} className="text-purple-400" />
                <h3 className="text-xs font-mono font-bold tracking-wider text-purple-400/90">MEMORY STREAM</h3>
              </div>
            </div>
            <div className="flex-1 px-4 pb-4 overflow-hidden">
              <MemoryStream memories={memories} maxEntries={100} onRefresh={onRefreshMemories} />
            </div>
          </div>
        )}

        {activeTab === 'logs' && (
          <div className="h-full flex flex-col p-2">
            <SystemConsole />
          </div>
        )}
      </div>
    </div>
  );
}
