"use client";

import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Play, Square, CheckCircle2, XCircle, Loader2, Brain,
  Wrench, AlertTriangle, ChevronDown, ChevronUp, Clock,
  ThumbsUp, ThumbsDown, Terminal, Zap, FileText
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { API_BASE_URL } from '@/config';

// ============================================================================
// TYPES
// ============================================================================

interface AgentStep {
  step: number;
  type: 'thinking' | 'tool_call' | 'tool_result' | 'response' | 'error' | 'waiting' | 'complete' | 'aborted';
  title: string;
  detail: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  result?: string;
  success: boolean;
  duration_ms: number;
  timestamp: number;
}

// ============================================================================
// STEP ICON + COLOR MAPPING
// ============================================================================

const STEP_STYLES: Record<string, { icon: React.ReactNode; color: string; bg: string; border: string }> = {
  thinking:    { icon: <Brain size={14} />,          color: 'text-blue-400',   bg: 'bg-blue-900/20',   border: 'border-blue-900/40' },
  tool_call:   { icon: <Wrench size={14} />,         color: 'text-cyan-400',   bg: 'bg-cyan-900/20',   border: 'border-cyan-900/40' },
  tool_result: { icon: <FileText size={14} />,       color: 'text-green-400',  bg: 'bg-green-900/20',  border: 'border-green-900/40' },
  response:    { icon: <Terminal size={14} />,        color: 'text-green-300',  bg: 'bg-green-900/15',  border: 'border-green-900/40' },
  error:       { icon: <XCircle size={14} />,         color: 'text-red-400',    bg: 'bg-red-900/20',    border: 'border-red-900/40' },
  waiting:     { icon: <AlertTriangle size={14} />,   color: 'text-yellow-400', bg: 'bg-yellow-900/20', border: 'border-yellow-900/40' },
  complete:    { icon: <CheckCircle2 size={14} />,    color: 'text-green-400',  bg: 'bg-green-900/25',  border: 'border-green-700/50' },
  aborted:     { icon: <Square size={14} />,          color: 'text-red-400',    bg: 'bg-red-900/20',    border: 'border-red-900/40' },
};

// ============================================================================
// COMPONENT
// ============================================================================

export default function AgentLoopPanel() {
  const [isExpanded, setIsExpanded] = useState(false);
  const [taskInput, setTaskInput] = useState('');
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Auto-scroll to bottom when new steps arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [steps]);

  // Start agent task
  const handleStart = useCallback(async () => {
    if (!taskInput.trim() || isRunning) return;

    setIsRunning(true);
    setSteps([]);
    setTaskId(null);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_BASE_URL}/agent/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: taskInput,
          max_iterations: 10,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Agent run failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event = JSON.parse(jsonStr);

            if (event.type === 'started') {
              setTaskId(event.task_id);
            } else if (event.type === 'stream_end') {
              // Done
            } else if (event.step !== undefined) {
              setSteps(prev => [...prev, event as AgentStep]);
            }
          } catch {
            // Skip malformed events
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        setSteps(prev => [...prev, {
          step: prev.length + 1,
          type: 'error',
          title: 'Connection failed',
          detail: err.message || 'Unknown error',
          success: false,
          duration_ms: 0,
          timestamp: Date.now() / 1000,
        }]);
      }
    } finally {
      setIsRunning(false);
      abortRef.current = null;
    }
  }, [taskInput, isRunning]);

  // Abort running task
  const handleAbort = useCallback(async () => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    if (taskId) {
      try {
        await fetch(`${API_BASE_URL}/agent/abort/${taskId}`, { method: 'POST' });
      } catch { /* best effort */ }
    }
    setIsRunning(false);
  }, [taskId]);

  // Approve/deny pending action
  const handleApproval = useCallback(async (approved: boolean) => {
    if (!taskId) return;
    try {
      await fetch(`${API_BASE_URL}/agent/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, approved }),
      });
    } catch (err) {
      console.error('Approval failed:', err);
    }
  }, [taskId]);

  const hasWaitingStep = steps.some(s => s.type === 'waiting' && !steps.some(later => later.step > s.step && (later.type === 'tool_call' || later.type === 'aborted')));

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full bg-black/40 border border-orange-900/50 rounded-lg backdrop-blur-sm overflow-hidden"
    >
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-orange-900/10 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="relative">
            <Zap size={16} className="text-orange-400" />
            {isRunning && (
              <div className="absolute -top-1 -right-1 w-2 h-2 bg-orange-500 rounded-full animate-pulse" />
            )}
          </div>
          <span className="font-mono text-sm text-orange-400">AGENT_LOOP</span>
          {isRunning && (
            <span className="text-[9px] font-mono px-2 py-0.5 rounded bg-orange-900/30 border border-orange-700/50 text-orange-300 animate-pulse">
              RUNNING
            </span>
          )}
          {steps.length > 0 && !isRunning && (
            <span className="text-[9px] font-mono px-2 py-0.5 rounded bg-green-900/30 border border-green-700/50 text-green-400">
              {steps.length} STEPS
            </span>
          )}
        </div>
        {isExpanded ? <ChevronUp size={16} className="text-orange-400" /> : <ChevronDown size={16} className="text-orange-400" />}
      </button>

      {/* Expanded Panel */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="border-t border-orange-900/50"
          >
            <div className="p-4 space-y-3">

              {/* Task Input */}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={taskInput}
                  onChange={(e) => setTaskInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleStart()}
                  placeholder="Give Aura an autonomous task..."
                  disabled={isRunning}
                  className="flex-1 bg-black/50 border border-orange-900/50 rounded px-3 py-2 text-orange-200 placeholder-orange-900/60 focus:outline-none focus:border-orange-500 font-mono text-sm disabled:opacity-50"
                />
                {isRunning ? (
                  <button
                    onClick={handleAbort}
                    className="px-4 py-2 rounded border border-red-700/50 bg-red-900/30 text-red-400 hover:bg-red-900/50 transition-colors font-mono text-sm"
                  >
                    <Square size={16} />
                  </button>
                ) : (
                  <button
                    onClick={handleStart}
                    disabled={!taskInput.trim()}
                    className="px-4 py-2 rounded border border-orange-700/50 bg-orange-900/30 text-orange-400 hover:bg-orange-900/50 transition-colors font-mono text-sm disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <Play size={16} />
                  </button>
                )}
              </div>

              {/* Approval Banner */}
              {hasWaitingStep && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex items-center justify-between p-3 bg-yellow-900/20 border border-yellow-700/50 rounded-lg"
                >
                  <div className="flex items-center gap-2">
                    <AlertTriangle size={16} className="text-yellow-400" />
                    <span className="font-mono text-xs text-yellow-300">APPROVAL REQUIRED</span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleApproval(true)}
                      className="flex items-center gap-1 px-3 py-1.5 rounded border border-green-700/50 bg-green-900/30 text-green-400 hover:bg-green-900/50 transition-colors text-xs font-mono"
                    >
                      <ThumbsUp size={12} /> APPROVE
                    </button>
                    <button
                      onClick={() => handleApproval(false)}
                      className="flex items-center gap-1 px-3 py-1.5 rounded border border-red-700/50 bg-red-900/30 text-red-400 hover:bg-red-900/50 transition-colors text-xs font-mono"
                    >
                      <ThumbsDown size={12} /> DENY
                    </button>
                  </div>
                </motion.div>
              )}

              {/* Step Log */}
              <div
                ref={scrollRef}
                className="max-h-80 overflow-y-auto space-y-1.5 custom-scrollbar"
              >
                {steps.length === 0 && !isRunning && (
                  <div className="text-center py-8 text-gray-600 font-mono text-xs">
                    Enter a task above to start an autonomous agent loop
                  </div>
                )}

                <AnimatePresence mode="popLayout">
                  {steps.map((step, idx) => {
                    const style = STEP_STYLES[step.type] || STEP_STYLES.thinking;
                    const isStepExpanded = expandedStep === idx;

                    return (
                      <motion.div
                        key={`${step.step}-${idx}`}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.2, delay: 0.05 }}
                        className={cn(
                          "rounded border p-2.5 cursor-pointer transition-colors",
                          style.bg, style.border,
                          isStepExpanded && "ring-1 ring-white/10"
                        )}
                        onClick={() => setExpandedStep(isStepExpanded ? null : idx)}
                      >
                        {/* Step Header */}
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 flex-1 min-w-0">
                            <span className={style.color}>{style.icon}</span>
                            <span className={cn("font-mono text-[11px] font-bold truncate", style.color)}>
                              {step.title}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                            {step.duration_ms > 0 && (
                              <span className="text-[9px] font-mono text-gray-500 flex items-center gap-0.5">
                                <Clock size={8} />
                                {step.duration_ms}ms
                              </span>
                            )}
                            {step.type === 'thinking' && (
                              <Loader2 size={10} className="text-blue-400 animate-spin" />
                            )}
                          </div>
                        </div>

                        {/* Step Detail (collapsed) */}
                        {step.detail && !isStepExpanded && (
                          <div className="mt-1 text-[10px] font-mono text-gray-500 truncate">
                            {step.detail}
                          </div>
                        )}

                        {/* Step Detail (expanded) */}
                        <AnimatePresence>
                          {isStepExpanded && (
                            <motion.div
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: 'auto', opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              className="mt-2 pt-2 border-t border-gray-800 space-y-1.5"
                            >
                              {step.detail && (
                                <div className="text-[10px] font-mono text-gray-400 whitespace-pre-wrap break-words">
                                  {step.detail}
                                </div>
                              )}
                              {step.tool_name && (
                                <div className="text-[10px] font-mono text-cyan-400">
                                  Tool: <span className="text-cyan-200">{step.tool_name}</span>
                                </div>
                              )}
                              {step.tool_args && (
                                <pre className="text-[9px] font-mono text-gray-500 bg-black/40 rounded p-2 overflow-x-auto max-h-32">
                                  {JSON.stringify(step.tool_args, null, 2)}
                                </pre>
                              )}
                              {step.result && (
                                <div className="text-[10px] font-mono text-gray-300 bg-black/30 rounded p-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words">
                                  {step.result}
                                </div>
                              )}
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </motion.div>
                    );
                  })}
                </AnimatePresence>

                {/* Running indicator */}
                {isRunning && (
                  <div className="flex items-center gap-2 p-2 text-orange-400">
                    <Loader2 size={12} className="animate-spin" />
                    <span className="text-[10px] font-mono">Processing...</span>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
