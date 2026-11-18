"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Moon,
  Loader2,
  Heart,
  Sparkles,
  Database,
  Activity,
  Shield,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE_URL } from "@/config";

// ============================================================================
// TYPES
// ============================================================================

interface MemoryIntrospectionData {
  total_memories: number;
  core_memories: number;
  ephemeral_pending_pruning: number;
  semantic_abstractions: number;
  oldest_memory: string | null;
  strongest_memory: {
    content: string;
    importance: number;
    recall_count: number;
  };
  most_emotional_memory: {
    content: string;
    emotional_intensity: number;
  };
  dominant_domains: string[];
  memory_health_score: number;
  last_dream_cycle: string | null;
  insights_count: number;
  knowledge_graph_edges: number;
}

interface DreamReport {
  pruned: number;
  abstracted: number;
  reprocessed: number;
  core_memories: number;
  total_active: number;
  timestamp: string;
}

// ============================================================================
// HEALTH GAUGE COMPONENT
// ============================================================================

function HealthGauge({ score }: { score: number }) {
  const circumference = 2 * Math.PI * 45;
  const filled = circumference * score;
  const healthColor =
    score > 0.7
      ? "stroke-amber-400"
      : score > 0.4
      ? "stroke-yellow-500"
      : "stroke-red-500";
  const glowColor =
    score > 0.7
      ? "drop-shadow(0 0 8px rgba(251, 191, 36, 0.6))"
      : score > 0.4
      ? "drop-shadow(0 0 8px rgba(234, 179, 8, 0.4))"
      : "drop-shadow(0 0 8px rgba(239, 68, 68, 0.4))";

  return (
    <div className="flex flex-col items-center">
      <svg
        width="120"
        height="120"
        viewBox="0 0 100 100"
        style={{ filter: glowColor }}
      >
        {/* Background circle */}
        <circle
          cx="50"
          cy="50"
          r="45"
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="6"
        />
        {/* Health arc */}
        <circle
          cx="50"
          cy="50"
          r="45"
          fill="none"
          className={healthColor}
          strokeWidth="6"
          strokeDasharray={`${filled} ${circumference}`}
          strokeDashoffset={circumference * 0.25}
          strokeLinecap="round"
          style={{
            transition: "stroke-dasharray 1s ease-out",
            transform: "rotate(-90deg)",
            transformOrigin: "50% 50%",
          }}
        />
        {/* Score text */}
        <text
          x="50"
          y="46"
          textAnchor="middle"
          className="fill-amber-300 text-lg font-bold"
          style={{ fontSize: "22px" }}
        >
          {Math.round(score * 100)}
        </text>
        <text
          x="50"
          y="62"
          textAnchor="middle"
          className="fill-amber-500/60 text-xs"
          style={{ fontSize: "10px" }}
        >
          HEALTH
        </text>
      </svg>
    </div>
  );
}

// ============================================================================
// STAT CARD
// ============================================================================

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="bg-black/30 border border-amber-900/20 rounded-lg p-3 flex items-center gap-3">
      <div className="p-2 rounded-md bg-amber-900/20">
        <Icon className="w-4 h-4 text-amber-400" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-amber-500/60 uppercase tracking-wider">
          {label}
        </p>
        <p className="text-sm font-semibold text-amber-200 truncate">
          {value}
        </p>
        {sub && (
          <p className="text-[10px] text-amber-500/40 truncate">{sub}</p>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// DOMAIN BAR
// ============================================================================

function DomainBar({
  domains,
}: {
  domains: string[];
}) {
  if (!domains.length) return null;
  const total = domains.length;

  return (
    <div className="space-y-1">
      <p className="text-xs text-amber-500/60 uppercase tracking-wider mb-2">
        Domain Distribution
      </p>
      <div className="flex gap-1 h-3 rounded-full overflow-hidden bg-black/30">
        {domains.map((d, i) => (
          <div
            key={`${d}-${i}`}
            className="h-full"
            style={{
              width: `${100 / total}%`,
              backgroundColor: `hsl(${35 + i * 25}, 80%, ${55 - i * 8}%)`,
            }}
            title={d}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-2 mt-1">
        {domains.map((d, i) => (
          <span
            key={`${d}-label-${i}`}
            className="text-[10px] text-amber-400/70 bg-amber-900/20 px-2 py-0.5 rounded-full"
          >
            {d}
          </span>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// MAIN PANEL
// ============================================================================

export default function MemoryIntrospectionPanel() {
  const [collapsed, setCollapsed] = useState(false);
  const [data, setData] = useState<MemoryIntrospectionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [dreaming, setDreaming] = useState(false);
  const [dreamReport, setDreamReport] = useState<DreamReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchIntrospection = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/memory/introspect/default`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.success) {
        setData(json);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  const triggerDream = useCallback(async () => {
    setDreaming(true);
    setDreamReport(null);
    try {
      const res = await fetch(`${API_BASE_URL}/memory/dream`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.success && json.report) {
        setDreamReport(json.report);
        // Refresh introspection data after dream
        await fetchIntrospection();
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Dream failed");
    } finally {
      setDreaming(false);
    }
  }, [fetchIntrospection]);

  useEffect(() => {
    fetchIntrospection();
  }, [fetchIntrospection]);

  const formatTimeAgo = (ts: string | null) => {
    if (!ts) return "Never";
    try {
      const d = new Date(ts);
      const now = new Date();
      const diff = (now.getTime() - d.getTime()) / 1000;
      if (diff < 60) return "Just now";
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    } catch {
      return ts;
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="border border-amber-900/30 bg-gradient-to-br from-gray-900/90 to-black/90 rounded-xl overflow-hidden"
    >
      {/* Header */}
      <div
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between p-4 hover:bg-amber-900/10 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <Brain className="w-5 h-5 text-amber-400" />
          <h3 className="text-sm font-semibold text-amber-300 tracking-wide">
            Memory Introspection
          </h3>
          {data && (
            <span className="text-[10px] text-amber-500/50 bg-amber-900/20 px-2 py-0.5 rounded-full">
              {data.total_memories} memories
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              fetchIntrospection();
            }}
            className="p-1 hover:bg-amber-900/20 rounded"
            title="Refresh"
          >
            <RefreshCw
              className={cn("w-3.5 h-3.5 text-amber-500", loading && "animate-spin")}
            />
          </button>
          {collapsed ? (
            <ChevronDown className="w-4 h-4 text-amber-500" />
          ) : (
            <ChevronUp className="w-4 h-4 text-amber-500" />
          )}
        </div>
      </div>

      <AnimatePresence>
        {!collapsed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="p-4 pt-0 space-y-4">
              {error && (
                <p className="text-xs text-red-400 bg-red-900/20 p-2 rounded">
                  {error}
                </p>
              )}

              {loading && !data && (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 text-amber-400 animate-spin" />
                </div>
              )}

              {data && (
                <>
                  {/* Health Gauge + Core Stats */}
                  <div className="flex items-center gap-6">
                    <HealthGauge score={data.memory_health_score} />
                    <div className="flex-1 grid grid-cols-2 gap-2">
                      <StatCard
                        icon={Shield}
                        label="Core"
                        value={data.core_memories}
                        sub="Protected memories"
                      />
                      <StatCard
                        icon={Sparkles}
                        label="Semantic"
                        value={data.semantic_abstractions}
                        sub="Abstracted insights"
                      />
                      <StatCard
                        icon={Zap}
                        label="Ephemeral"
                        value={data.ephemeral_pending_pruning}
                        sub="Pending pruning"
                      />
                      <StatCard
                        icon={Database}
                        label="Graph"
                        value={data.knowledge_graph_edges}
                        sub="Related edges"
                      />
                    </div>
                  </div>

                  {/* Insights + Total */}
                  <div className="grid grid-cols-3 gap-2">
                    <StatCard
                      icon={Brain}
                      label="Total"
                      value={data.total_memories}
                    />
                    <StatCard
                      icon={Activity}
                      label="Insights"
                      value={data.insights_count}
                    />
                    <StatCard
                      icon={Moon}
                      label="Last Dream"
                      value={formatTimeAgo(data.last_dream_cycle)}
                    />
                  </div>

                  {/* Domain Distribution */}
                  <DomainBar domains={data.dominant_domains} />

                  {/* Strongest Memory */}
                  {data.strongest_memory?.content && (
                    <div className="bg-black/30 border border-amber-900/20 rounded-lg p-3">
                      <p className="text-xs text-amber-500/60 uppercase tracking-wider mb-1">
                        Strongest Memory
                      </p>
                      <p className="text-xs text-amber-200 line-clamp-2">
                        {data.strongest_memory.content}
                      </p>
                      <p className="text-[10px] text-amber-500/40 mt-1">
                        importance: {data.strongest_memory.importance} · recalled{" "}
                        {data.strongest_memory.recall_count}x
                      </p>
                    </div>
                  )}

                  {/* Most Emotional Memory */}
                  {data.most_emotional_memory?.content && (
                    <div className="bg-black/30 border border-amber-900/20 rounded-lg p-3">
                      <div className="flex items-center gap-1 mb-1">
                        <Heart className="w-3 h-3 text-rose-400" />
                        <p className="text-xs text-amber-500/60 uppercase tracking-wider">
                          Most Emotional
                        </p>
                      </div>
                      <p className="text-xs text-amber-200 line-clamp-2">
                        {data.most_emotional_memory.content}
                      </p>
                      <p className="text-[10px] text-amber-500/40 mt-1">
                        intensity:{" "}
                        {typeof data.most_emotional_memory.emotional_intensity === "number"
                          ? data.most_emotional_memory.emotional_intensity.toFixed(2)
                          : data.most_emotional_memory.emotional_intensity}
                      </p>
                    </div>
                  )}

                  {/* Dream Report (if just dreamed) */}
                  <AnimatePresence>
                    {dreamReport && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        className="bg-indigo-950/30 border border-indigo-800/30 rounded-lg p-3"
                      >
                        <p className="text-xs text-indigo-300 font-semibold mb-2">
                          🌙 Dream Report
                        </p>
                        <div className="grid grid-cols-3 gap-2 text-center">
                          <div>
                            <p className="text-lg font-bold text-indigo-200">
                              {dreamReport.pruned}
                            </p>
                            <p className="text-[10px] text-indigo-400">Pruned</p>
                          </div>
                          <div>
                            <p className="text-lg font-bold text-indigo-200">
                              {dreamReport.abstracted}
                            </p>
                            <p className="text-[10px] text-indigo-400">
                              Abstracted
                            </p>
                          </div>
                          <div>
                            <p className="text-lg font-bold text-indigo-200">
                              {dreamReport.reprocessed}
                            </p>
                            <p className="text-[10px] text-indigo-400">
                              Reprocessed
                            </p>
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Dream Now Button */}
                  <button
                    onClick={triggerDream}
                    disabled={dreaming}
                    className={cn(
                      "w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all",
                      dreaming
                        ? "bg-indigo-900/30 text-indigo-400 cursor-wait"
                        : "bg-amber-900/20 hover:bg-amber-900/40 text-amber-300 border border-amber-800/30"
                    )}
                  >
                    {dreaming ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Dreaming...
                      </>
                    ) : (
                      <>
                        <Moon className="w-4 h-4" />
                        DREAM NOW
                      </>
                    )}
                  </button>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
