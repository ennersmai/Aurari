import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Code, Wrench, RefreshCw, AlertCircle, Copy, Check, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { API_BASE_URL } from '@/config';
import { useSettings } from '@/contexts/SettingsContext';

interface Skill {
  skill_id: string;
  name: string;
  domain: string;
  mastery_level: number;
  skill_type: string;
  created: string;
  last_practiced: string | null;
  emotional_signature: Record<string, number>;
  parent_skill_id: string | null;
  sub_skill_ids: string[];
  execution_config?: Record<string, unknown>;
  definition?: unknown;
}

interface SystemContext {
  user_id: string;
  context: string;
  has_context: boolean;
}

type TabType = 'skills' | 'context';

export default function SystemDebugPanel() {
  const [activeTab, setActiveTab] = useState<TabType>('skills');
  const [skills, setSkills] = useState<Skill[]>([]);
  const [systemContext, setSystemContext] = useState<SystemContext | null>(null);
  const [isLoadingSkills, setIsLoadingSkills] = useState(false);
  const [isLoadingContext, setIsLoadingContext] = useState(false);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [deletingSkillId, setDeletingSkillId] = useState<string | null>(null);

  const [expandedSkillId, setExpandedSkillId] = useState<string | null>(null);
  const [triggersBySkillId, setTriggersBySkillId] = useState<Record<string, string[]>>({});
  const [loadingTriggersForSkillId, setLoadingTriggersForSkillId] = useState<string | null>(null);
  const [triggersErrorBySkillId, setTriggersErrorBySkillId] = useState<Record<string, string | null>>({});

  const hasFetchedSkills = useRef(false);
  const hasFetchedContext = useRef(false);

  const { settings } = useSettings();
  const commanderIdentity = settings.commanderIdentity || "Mai";

  const formatValue = useCallback((value: unknown, maxLen = 220) => {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value.length > maxLen ? value.slice(0, maxLen) + '\u2026' : value;
    try {
      const json = JSON.stringify(value, null, 2);
      return json.length > maxLen ? json.slice(0, maxLen) + '\u2026' : json;
    } catch {
      return String(value);
    }
  }, []);

  const fetchSkills = useCallback(async () => {
    if (isLoadingSkills) return;
    setIsLoadingSkills(true);
    setSkillsError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/learning/skills/registry`);
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      const data = await response.json();
      if (data.success && Array.isArray(data.skills)) {
        setSkills(data.skills);
        hasFetchedSkills.current = true;
      } else {
        throw new Error('Invalid response format');
      }
    } catch (error) {
      console.error('Failed to fetch skills:', error);
      setSkillsError(error instanceof Error ? error.message : 'Failed to load skills');
    } finally {
      setIsLoadingSkills(false);
    }
  }, [isLoadingSkills]);

  const fetchTriggersForSkill = useCallback(async (skillId: string) => {
    if (loadingTriggersForSkillId) return;
    setLoadingTriggersForSkillId(skillId);
    setTriggersErrorBySkillId(prev => ({ ...prev, [skillId]: null }));
    try {
      const response = await fetch(`${API_BASE_URL}/learning/skills/${encodeURIComponent(skillId)}/triggers`);
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      const data = await response.json();
      if (data.success && Array.isArray(data.triggers)) {
        setTriggersBySkillId(prev => ({ ...prev, [skillId]: data.triggers }));
      } else {
        throw new Error('Invalid response format');
      }
    } catch (error) {
      console.error('Failed to fetch triggers:', error);
      setTriggersErrorBySkillId(prev => ({
        ...prev,
        [skillId]: error instanceof Error ? error.message : 'Failed to load triggers'
      }));
    } finally {
      setLoadingTriggersForSkillId(null);
    }
  }, [loadingTriggersForSkillId]);

  const fetchSystemContext = useCallback(async () => {
    if (isLoadingContext) return;
    setIsLoadingContext(true);
    setContextError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/chat/debug/last_context/${commanderIdentity}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      const data = await response.json();
      if (data.success) {
        setSystemContext(data);
        hasFetchedContext.current = true;
      } else {
        throw new Error('Invalid response format');
      }
    } catch (error) {
      console.error('Failed to fetch system context:', error);
      setContextError(error instanceof Error ? error.message : 'Failed to load context');
    } finally {
      setIsLoadingContext(false);
    }
  }, [commanderIdentity, isLoadingContext]);

  useEffect(() => {
    if (activeTab === 'skills' && !hasFetchedSkills.current && !isLoadingSkills) {
      fetchSkills();
    }
  }, [activeTab, fetchSkills, isLoadingSkills]);

  useEffect(() => {
    if (activeTab === 'context' && !hasFetchedContext.current && !isLoadingContext) {
      fetchSystemContext();
    }
  }, [activeTab, fetchSystemContext, isLoadingContext]);

  const copyToClipboard = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy:', error);
    }
  }, []);

  const deleteSkill = useCallback(async (skillId: string) => {
    if (!confirm(`Are you sure you want to delete this skill? This will permanently remove it from the database.`)) {
      return;
    }
    setDeletingSkillId(skillId);
    try {
      const response = await fetch(`${API_BASE_URL}/learning/skills/${encodeURIComponent(skillId)}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.success) {
        setSkills(prevSkills => prevSkills.filter(skill => skill.skill_id !== skillId));
        hasFetchedSkills.current = false;
      } else {
        throw new Error(data.detail || 'Failed to delete skill');
      }
    } catch (error) {
      console.error('Failed to delete skill:', error);
      alert(`Failed to delete skill: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setDeletingSkillId(null);
    }
  }, []);

  const tabs = [
    { id: 'skills' as TabType, label: 'SKILLS', icon: Wrench, color: 'amber' },
    { id: 'context' as TabType, label: 'CONTEXT', icon: Code, color: 'cyan' },
  ];

  const tabColors: Record<string, { border: string; bg: string; text: string; muted: string }> = {
    amber: { border: '#eab308', bg: 'rgba(234,179,8,0.1)', text: '#facc15', muted: 'rgba(234,179,8,0.25)' },
    cyan: { border: '#06b6d4', bg: 'rgba(6,182,212,0.1)', text: '#22d3ee', muted: 'rgba(6,182,212,0.25)' },
  };

  return (
    <div className="h-full w-full flex flex-col" style={{
      minHeight: 0,
      background: 'rgba(14, 14, 18, 0.92)',
      border: '1px solid rgba(255,255,255,0.06)',
      borderRadius: '16px',
      overflow: 'hidden',
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
                color: c.text,
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
        <AnimatePresence mode="wait">
          {activeTab === 'skills' && (
            <motion.div
              key="skills"
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 16 }}
              transition={{ duration: 0.2 }}
              className="p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Wrench size={14} className="text-amber-400" />
                  <h3 className="text-xs font-mono font-bold tracking-wider text-amber-400/90">SKILL REGISTRY</h3>
                </div>
                <button
                  onClick={() => { hasFetchedSkills.current = false; fetchSkills(); }}
                  disabled={isLoadingSkills}
                  className="glass-btn-icon w-7 h-7"
                >
                  <RefreshCw size={11} className={cn("text-amber-400", isLoadingSkills && "animate-spin")} />
                </button>
              </div>

              {isLoadingSkills && (
                <div className="flex items-center justify-center py-8">
                  <div className="text-center space-y-2">
                    <RefreshCw size={22} className="mx-auto text-amber-400 animate-spin" />
                    <p className="text-[10px] font-mono text-gray-500">Loading skills...</p>
                  </div>
                </div>
              )}

              {skillsError && !isLoadingSkills && (
                <div className="flex items-center gap-2 p-3 rounded-lg text-[10px] font-mono text-red-400"
                  style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
                  <AlertCircle size={12} />
                  <span>{skillsError}</span>
                </div>
              )}

              {!isLoadingSkills && !skillsError && skills.length > 0 && (
                <div className="space-y-2">
                  <div className="text-[9px] font-mono text-gray-500">
                    COUNT: <span className="text-amber-400">{skills.length}</span>
                  </div>
                  {skills.map((skill) => (
                    <motion.div
                      key={skill.skill_id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, scale: 0.96 }}
                      className="group p-3 rounded-lg transition-colors"
                      style={{
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid',
                        borderColor:
                          skill.skill_type === 'local_function' ? 'rgba(251,191,36,0.2)' :
                          skill.skill_type === 'abstract' ? 'rgba(59,130,246,0.2)' :
                          'rgba(168,85,247,0.2)'
                      }}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span
                            className="text-[9px] font-mono font-bold px-2 py-0.5 rounded-md"
                            style={{
                              backgroundColor:
                                skill.skill_type === 'local_function' ? 'rgba(251,191,36,0.15)' :
                                skill.skill_type === 'abstract' ? 'rgba(59,130,246,0.15)' :
                                'rgba(168,85,247,0.15)',
                              color:
                                skill.skill_type === 'local_function' ? '#fbbf24' :
                                skill.skill_type === 'abstract' ? '#60a5fa' :
                                '#c084fc'
                            }}
                          >
                            {skill.skill_type.toUpperCase()}
                          </span>
                          <span className="text-[11px] font-mono font-bold text-gray-200">{skill.name}</span>
                        </div>
                        <button
                          onClick={() => deleteSkill(skill.skill_id)}
                          disabled={deletingSkillId === skill.skill_id}
                          className="glass-btn-icon w-6 h-6 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <Trash2 size={11} className="text-red-400" />
                        </button>
                      </div>

                      <div className="space-y-1 text-[10px] font-mono text-gray-300">
                        <div>
                          <span className="text-gray-500">Domain:</span> <span className="text-amber-400/80">{skill.domain}</span>
                        </div>
                        <div>
                          <span className="text-gray-500">Mastery:</span> <span className="text-emerald-400/80">{(skill.mastery_level * 100).toFixed(0)}%</span>
                        </div>
                        {skill.execution_config && (
                          <div className="text-[9px] text-gray-400">
                            <span className="text-gray-500">Config:</span> {formatValue(skill.execution_config, 140)}
                          </div>
                        )}
                        {skill.definition != null && (
                          <div className="text-[9px] text-gray-400 mt-1">
                            <span className="text-gray-500">Definition:</span>
                            <pre className="mt-1 whitespace-pre-wrap break-words text-[9px] text-gray-400 rounded-lg p-2"
                              style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                              {formatValue(skill.definition, 1200)}
                            </pre>
                          </div>
                        )}
                      </div>

                      {skill.skill_type === 'local_function' && (
                        <div className="mt-2 pt-2 border-t border-white/[0.04]">
                          <div className="flex items-center justify-between">
                            <button
                              className="text-[9px] font-mono text-amber-400/80 hover:text-amber-300 transition-colors"
                              onClick={() => {
                                const next = expandedSkillId === skill.skill_id ? null : skill.skill_id;
                                setExpandedSkillId(next);
                                if (next && !triggersBySkillId[next]) {
                                  fetchTriggersForSkill(next);
                                }
                              }}
                            >
                              {expandedSkillId === skill.skill_id ? 'Hide triggers' : 'Show triggers'}
                            </button>
                            {expandedSkillId === skill.skill_id && (
                              <button
                                className="text-[9px] font-mono text-gray-500 hover:text-gray-300"
                                disabled={loadingTriggersForSkillId === skill.skill_id}
                                onClick={() => fetchTriggersForSkill(skill.skill_id)}
                              >
                                {loadingTriggersForSkillId === skill.skill_id ? 'Loading\u2026' : 'Refresh'}
                              </button>
                            )}
                          </div>

                          {expandedSkillId === skill.skill_id && (
                            <div className="mt-2">
                              {triggersErrorBySkillId[skill.skill_id] && (
                                <div className="text-[9px] font-mono text-red-400">
                                  {triggersErrorBySkillId[skill.skill_id]}
                                </div>
                              )}
                              {!triggersErrorBySkillId[skill.skill_id] && (
                                <div className="space-y-1">
                                  <div className="text-[9px] font-mono text-gray-500">
                                    TRIGGERS: <span className="text-amber-400">{(triggersBySkillId[skill.skill_id] || []).length}</span>
                                  </div>
                                  <ul className="list-disc pl-4 text-[9px] font-mono text-gray-400 space-y-0.5">
                                    {(triggersBySkillId[skill.skill_id] || []).map((t, idx) => (
                                      <li key={`${skill.skill_id}-t-${idx}`} className="break-words">{t}</li>
                                    ))}
                                  </ul>
                                  {(triggersBySkillId[skill.skill_id] || []).length === 0 && (
                                    <div className="text-[9px] font-mono text-gray-600">
                                      None yet — triggers are generated in the background right after ingest.
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )}

                      <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/[0.04] text-[8px] font-mono text-gray-600">
                        <span className="text-gray-500">ID: {skill.skill_id.substring(0, 20)}...</span>
                        {skill.sub_skill_ids.length > 0 && (
                          <span className="text-gray-400">{skill.sub_skill_ids.length} sub-skills</span>
                        )}
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}

              {!isLoadingSkills && !skillsError && skills.length === 0 && (
                <div className="flex items-center justify-center py-8">
                  <div className="text-center space-y-2">
                    <Wrench size={28} className="mx-auto text-amber-800" />
                    <p className="text-[10px] font-mono text-gray-500">No skills registered yet</p>
                    <p className="text-[8px] font-mono text-gray-600">
                      Skills will appear here as Aura learns new capabilities
                    </p>
                  </div>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'context' && (
            <motion.div
              key="context"
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 16 }}
              transition={{ duration: 0.2 }}
              className="p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Code size={14} className="text-cyan-400" />
                  <h3 className="text-xs font-mono font-bold tracking-wider text-cyan-400/90">L3 SYSTEM CONTEXT</h3>
                </div>
                <div className="flex items-center gap-1.5">
                  {systemContext && systemContext.has_context && (
                    <button
                      onClick={() => copyToClipboard(systemContext.context)}
                      className="glass-btn-icon w-7 h-7"
                      title="Copy context"
                    >
                      {copied ? <Check size={11} className="text-cyan-400" /> : <Copy size={11} className="text-cyan-400" />}
                    </button>
                  )}
                  <button
                    onClick={() => { hasFetchedContext.current = false; fetchSystemContext(); }}
                    disabled={isLoadingContext}
                    className="glass-btn-icon w-7 h-7"
                    title="Refresh context"
                  >
                    <RefreshCw size={11} className={cn("text-cyan-400", isLoadingContext && "animate-spin")} />
                  </button>
                </div>
              </div>

              {isLoadingContext && (
                <div className="flex items-center justify-center py-8">
                  <div className="text-center space-y-2">
                    <RefreshCw size={22} className="mx-auto text-cyan-400 animate-spin" />
                    <p className="text-[10px] font-mono text-gray-500">Loading context...</p>
                  </div>
                </div>
              )}

              {contextError && !isLoadingContext && (
                <div className="flex items-center gap-2 p-3 rounded-lg text-[10px] font-mono text-red-400"
                  style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
                  <AlertCircle size={12} />
                  <span>{contextError}</span>
                </div>
              )}

              {!isLoadingContext && !contextError && systemContext && (
                <div className="space-y-2">
                  {systemContext.has_context ? (
                    <div className="glass-panel-sm p-3"
                      style={{ borderColor: 'rgba(6,182,212,0.2)' }}>
                      <div className="text-[9px] font-mono text-gray-500 mb-2">
                        USER: <span className="text-cyan-400">{systemContext.user_id}</span>
                      </div>
                      <pre className="text-[10px] font-mono text-gray-300 whitespace-pre-wrap break-words overflow-x-auto">
                        {systemContext.context}
                      </pre>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center py-8">
                      <div className="text-center space-y-2">
                        <Code size={28} className="mx-auto text-cyan-800" />
                        <p className="text-[10px] font-mono text-gray-500">No context recorded yet</p>
                        <p className="text-[8px] font-mono text-gray-600">
                          Send a message to see the L3 system prompt
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
