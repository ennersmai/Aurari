/**
 * TaskTimeline — Horizontal timeline showing the full emotional and execution
 * arc of a task. Renders step marks color-coded by type, a continuous resonance
 * line graph, and supports hover tooltips, click-to-jump, and real-time
 * streaming of new steps via SSE.
 *
 * Visual language: dark background, amber resonance line, colored step marks,
 * subtle glow on hover. Feels like an ECG of Aura's work.
 */

/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity, AlertTriangle, Brain, CheckCircle2, ChevronDown,
  ChevronUp, Clock, Play, Star, XCircle, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ============================================================================
// TYPES
// ============================================================================

export interface TimelineStep {
  step_number: number;
  step_type: string;
  title: string;
  detail: string;
  tool_name?: string;
  tool_args?: Record<string, any>;
  result?: string;
  success: boolean;
  duration_ms: number;
  timestamp: number;
  emotional_state_snapshot?: {
    dominant_emotion: string;
    valence: number;
    arousal: number;
    top_emotions: Record<string, number>;
  } | null;
  active_file?: string | null;
}

interface TaskTimelineProps {
  steps: TimelineStep[];
  resonanceScores: number[];
  createdAt: string;
  completedAt: string | null;
  isLive: boolean;
  onStepClick?: (step: TimelineStep) => void;
  /** Replay mode: externally controlled scrubber position */
  replayIndex?: number | null;
  onReplaySeek?: (index: number) => void;
}

// ============================================================================
// CONSTANTS
// ============================================================================

const MARK_COLORS: Record<string, string> = {
  thinking: "#6b7280",      // gray
  tool_call: "#d97706",     // amber
  tool_result_ok: "#16a34a", // green
  tool_result_fail: "#dc2626", // red
  error: "#dc2626",
  escalation: "#dc2626",
  complete: "#eab308",      // gold
  response: "#8b5cf6",      // purple
  warning: "#f59e0b",       // yellow
  aborted: "#6b7280",
};

function getMarkColor(step: TimelineStep): string {
  if (step.step_type === "tool_result") {
    return step.success ? MARK_COLORS.tool_result_ok : MARK_COLORS.tool_result_fail;
  }
  return MARK_COLORS[step.step_type] || MARK_COLORS.thinking;
}

function getMarkIcon(step: TimelineStep) {
  if (step.step_type === "escalation") return <AlertTriangle size={8} />;
  if (step.step_type === "complete") return <Star size={8} />;
  if (step.step_type === "error") return <XCircle size={8} />;
  return null;
}

// ============================================================================
// TOOLTIP
// ============================================================================

function StepTooltip({ step, x, y }: { step: TimelineStep; x: number; y: number }) {
  const emo = step.emotional_state_snapshot;
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="fixed z-50 pointer-events-none"
      style={{ left: x, top: y - 8, transform: "translate(-50%, -100%)" }}
    >
      <div className="bg-black/95 border border-amber-900/40 rounded-md px-3 py-2 shadow-lg shadow-amber-900/10 max-w-xs">
        <div className="text-[10px] font-mono text-amber-300 font-bold mb-1 truncate">
          {step.title}
        </div>
        {step.detail && (
          <div className="text-[9px] font-mono text-gray-400 mb-1 line-clamp-2">
            {step.detail.slice(0, 150)}
          </div>
        )}
        <div className="flex items-center gap-3 text-[8px] font-mono text-gray-500">
          {step.tool_name && <span>TOOL: {step.tool_name}</span>}
          {step.duration_ms > 0 && <span>{step.duration_ms}ms</span>}
          {emo && (
            <span className="text-amber-500">
              {emo.dominant_emotion} ({(emo.valence >= 0 ? "+" : "")}{emo.valence.toFixed(2)})
            </span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function TaskTimeline({
  steps,
  resonanceScores,
  createdAt,
  completedAt,
  isLive,
  onStepClick,
  replayIndex,
  onReplaySeek,
}: TaskTimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoveredStep, setHoveredStep] = useState<{ step: TimelineStep; x: number; y: number } | null>(null);
  const [isExpanded, setIsExpanded] = useState(true);

  // Filter out heartbeats — they're not visual steps
  const visualSteps = useMemo(
    () => steps.filter((s) => s.step_type !== "heartbeat"),
    [steps],
  );

  // Time range
  const timeRange = useMemo(() => {
    const start = new Date(createdAt).getTime() / 1000;
    const end = completedAt
      ? new Date(completedAt).getTime() / 1000
      : visualSteps.length > 0
        ? Math.max(...visualSteps.map((s) => s.timestamp)) + 1
        : start + 1;
    return { start, end, duration: Math.max(end - start, 1) };
  }, [createdAt, completedAt, visualSteps]);

  // Draw the resonance line on canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || resonanceScores.length < 2) return;

    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = 40 * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = "40px";

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, 40);

    // Draw resonance line
    ctx.beginPath();
    ctx.strokeStyle = "#d97706";
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";

    const w = rect.width;
    const h = 36;
    const pad = 2;

    for (let i = 0; i < resonanceScores.length; i++) {
      const x = (i / (resonanceScores.length - 1)) * w;
      const y = pad + h - resonanceScores[i] * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Gradient fill under the line
    const gradient = ctx.createLinearGradient(0, 0, 0, 40);
    gradient.addColorStop(0, "rgba(217, 119, 6, 0.15)");
    gradient.addColorStop(1, "rgba(217, 119, 6, 0.0)");

    ctx.lineTo(w, 40);
    ctx.lineTo(0, 40);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
  }, [resonanceScores, isExpanded]);

  // Auto-scroll to the right when live
  useEffect(() => {
    if (isLive && containerRef.current) {
      containerRef.current.scrollLeft = containerRef.current.scrollWidth;
    }
  }, [visualSteps.length, isLive]);

  const handleStepHover = useCallback(
    (step: TimelineStep, e: React.MouseEvent) => {
      setHoveredStep({ step, x: e.clientX, y: e.clientY });
    },
    [],
  );

  if (visualSteps.length === 0) return null;

  return (
    <div className="border-t border-amber-900/30 bg-black/60">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full h-7 px-3 flex items-center justify-between text-[10px] font-mono text-amber-500 hover:bg-amber-900/10 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Activity size={11} />
          <span>TIMELINE</span>
          <span className="text-gray-600">({visualSteps.length} steps)</span>
          {isLive && (
            <span className="flex items-center gap-1 text-amber-400">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
              LIVE
            </span>
          )}
        </div>
        {isExpanded ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
      </button>

      {isExpanded && (
        <div className="relative px-3 pb-2">
          {/* Resonance line canvas */}
          {resonanceScores.length >= 2 && (
            <canvas
              ref={canvasRef}
              className="w-full pointer-events-none"
              style={{ height: "40px" }}
            />
          )}

          {/* Step marks */}
          <div
            ref={containerRef}
            className="relative h-8 overflow-x-auto overflow-y-hidden custom-scrollbar"
          >
            {/* Base line */}
            <div className="absolute top-1/2 left-0 right-0 h-px bg-amber-900/30" />

            {/* Marks container — min-width ensures scrollability */}
            <div
              className="relative h-full"
              style={{
                minWidth: `${Math.max(visualSteps.length * 18, 200)}px`,
              }}
            >
              {visualSteps.map((step, idx) => {
                const pct =
                  visualSteps.length > 1
                    ? (idx / (visualSteps.length - 1)) * 100
                    : 50;
                const color = getMarkColor(step);
                const _icon = getMarkIcon(step);
                const isReplayCurrent = replayIndex !== null && replayIndex !== undefined && idx === replayIndex;
                const isEscalation = step.step_type === "escalation";
                const isComplete = step.step_type === "complete";

                return (
                  <motion.button
                    key={step.step_number}
                    initial={isLive ? { scale: 0, opacity: 0 } : false}
                    animate={{
                      scale: isReplayCurrent ? 1.6 : 1,
                      opacity: 1,
                    }}
                    transition={{ type: "spring", stiffness: 500, damping: 25 }}
                    className={cn(
                      "absolute top-1/2 -translate-y-1/2 -translate-x-1/2 flex items-center justify-center transition-all cursor-pointer group",
                      isEscalation ? "w-3 h-4" : isComplete ? "w-3 h-3" : "w-2 h-2",
                    )}
                    style={{
                      left: `${pct}%`,
                    }}
                    onClick={() => {
                      if (onReplaySeek) onReplaySeek(idx);
                      if (onStepClick) onStepClick(step);
                    }}
                    onMouseEnter={(e) => handleStepHover(step, e)}
                    onMouseLeave={() => setHoveredStep(null)}
                  >
                    {/* Mark shape */}
                    {isEscalation ? (
                      <div
                        className="w-0 h-0 border-l-[5px] border-r-[5px] border-b-[8px] border-l-transparent border-r-transparent"
                        style={{ borderBottomColor: color }}
                      />
                    ) : isComplete ? (
                      <Star
                        size={10}
                        className="fill-current"
                        style={{ color }}
                      />
                    ) : (
                      <div
                        className="w-full h-full rounded-full group-hover:ring-2 group-hover:ring-offset-1 group-hover:ring-offset-black transition-all"
                        style={{
                          backgroundColor: color,
                          boxShadow: isReplayCurrent
                            ? `0 0 8px ${color}`
                            : undefined,
                        }}
                      />
                    )}
                  </motion.button>
                );
              })}
            </div>
          </div>

          {/* Time labels */}
          <div className="flex justify-between text-[8px] font-mono text-gray-700 mt-0.5 px-1">
            <span>{new Date(timeRange.start * 1000).toLocaleTimeString()}</span>
            <span>
              {completedAt
                ? new Date(timeRange.end * 1000).toLocaleTimeString()
                : "now"}
            </span>
          </div>

          {/* Replay scrubber (only in replay mode) */}
          {replayIndex !== null && replayIndex !== undefined && onReplaySeek && (
            <div className="mt-1">
              <input
                type="range"
                min={0}
                max={Math.max(visualSteps.length - 1, 0)}
                value={replayIndex}
                onChange={(e) => onReplaySeek(Number(e.target.value))}
                className="w-full h-1 appearance-none bg-amber-900/30 rounded-full cursor-pointer
                  [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                  [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-amber-500
                  [&::-webkit-slider-thumb]:shadow-[0_0_6px_rgba(217,119,6,0.5)]"
              />
            </div>
          )}
        </div>
      )}

      {/* Tooltip */}
      <AnimatePresence>
        {hoveredStep && (
          <StepTooltip
            step={hoveredStep.step}
            x={hoveredStep.x}
            y={hoveredStep.y}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
