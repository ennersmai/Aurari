"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Globe,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  CheckCircle2,
  Loader2,
  Users,
  Shield,
  Waves,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE_URL } from "@/config";

// ============================================================================
// TYPES
// ============================================================================

interface CulturalNode {
  code: string;
  name: string;
  communication_style: string;
  collective_weight: number;
  restraint_bias: number;
  key_concepts: Record<string, string>;
  ethical_principles: string[];
  is_active: boolean;
  confidence_level: number;
}

interface RoutingDecision {
  timestamp: string;
  selected_node: string;
  detection_method: string;
  confidence: number;
  reason: string;
  user_id: string | null;
}

interface ActiveState {
  active_node: string | null;
  node: CulturalNode | null;
  last_decision: RoutingDecision | null;
}

// ============================================================================
// COMPONENT
// ============================================================================

export default function CulturalPanel() {
  const [isExpanded, setIsExpanded] = useState(false);
  const [nodes, setNodes] = useState<CulturalNode[]>([]);
  const [activeState, setActiveState] = useState<ActiveState | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [resonanceScore, setResonanceScore] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<string | null>(null);

  // ---- Fetch all nodes ----
  const fetchNodes = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/cultural/nodes`);
      if (res.ok) {
        const data = await res.json();
        setNodes(data.nodes || []);
      }
    } catch (e) {
      console.error("Failed to fetch cultural nodes:", e);
    }
  }, []);

  // ---- Fetch active node ----
  const fetchActive = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/cultural/active`);
      if (res.ok) {
        const data = await res.json();
        setActiveState(data);
      }
    } catch (e) {
      console.error("Failed to fetch active cultural node:", e);
    }
  }, []);

  // ---- Select a node manually ----
  const selectNode = useCallback(
    async (code: string) => {
      setSwitching(true);
      try {
        const res = await fetch(`${API_BASE_URL}/cultural/route`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ explicit_preference: code }),
        });
        if (res.ok) {
          await fetchActive();
        }
      } catch (e) {
        console.error("Failed to select cultural node:", e);
      } finally {
        setSwitching(false);
      }
    },
    [fetchActive]
  );

  // ---- Initial load ----
  useEffect(() => {
    if (isExpanded && nodes.length === 0) {
      setLoading(true);
      Promise.all([fetchNodes(), fetchActive()]).finally(() =>
        setLoading(false)
      );
    }
  }, [isExpanded, nodes.length, fetchNodes, fetchActive]);

  // ---- Periodic refresh for resonance + active node ----
  useEffect(() => {
    if (!isExpanded) return;
    const interval = setInterval(fetchActive, 15000);
    return () => clearInterval(interval);
  }, [isExpanded, fetchActive]);

  // ---- Helpers ----
  const activeCode = activeState?.active_node;

  const restraintLabel = (bias: number) => {
    if (bias >= 0.5) return "Strong";
    if (bias >= 0.2) return "Moderate";
    if (bias > -0.2) return "Balanced";
    return "Action-biased";
  };

  const restraintColor = (bias: number) => {
    if (bias >= 0.5) return "text-blue-400";
    if (bias >= 0.2) return "text-cyan-400";
    if (bias > -0.2) return "text-gray-400";
    return "text-orange-400";
  };

  const collectiveLabel = (w: number) => {
    if (w >= 0.7) return "Collectivist";
    if (w >= 0.4) return "Balanced";
    return "Individualist";
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full bg-black/40 border border-amber-900/50 rounded-lg backdrop-blur-sm overflow-hidden"
    >
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-amber-900/10 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Globe size={16} className="text-amber-400" />
          <span className="font-mono text-sm text-amber-400">
            CULTURAL_ROUTER
          </span>
          {activeCode && (
            <span className="text-[10px] bg-amber-900/40 border border-amber-700/50 text-amber-300 px-2 py-0.5 rounded font-mono">
              {activeCode}
            </span>
          )}
          {resonanceScore !== null && (
            <span className="text-[10px] bg-emerald-900/30 border border-emerald-700/40 text-emerald-400 px-2 py-0.5 rounded font-mono flex items-center gap-1">
              <Waves size={10} />
              {resonanceScore.toFixed(2)}
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp size={16} className="text-amber-400" />
        ) : (
          <ChevronDown size={16} className="text-amber-400" />
        )}
      </button>

      {/* Panel Body */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-amber-900/50"
          >
            <div className="p-4 space-y-4">
              {loading ? (
                <div className="flex items-center justify-center py-8 gap-2 text-amber-500 text-sm font-mono">
                  <Loader2 size={16} className="animate-spin" />
                  Loading cultural nodes...
                </div>
              ) : (
                <>
                  {/* Resonance Score Display */}
                  {activeState?.last_decision && (
                    <div className="bg-black/30 border border-emerald-900/30 rounded-lg p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <Waves size={14} className="text-emerald-400" />
                        <span className="text-xs font-mono text-emerald-400">
                          RESONANCE_FIELD
                        </span>
                      </div>
                      <div className="text-[10px] font-mono text-gray-400 space-y-1">
                        <div>
                          <span className="text-gray-500">LAST_ROUTE:</span>{" "}
                          <span className="text-amber-300">
                            {activeState.last_decision.detection_method}
                          </span>{" "}
                          →{" "}
                          <span className="text-amber-200">
                            {activeState.last_decision.selected_node}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500">CONFIDENCE:</span>{" "}
                          <span className="text-emerald-300">
                            {(
                              activeState.last_decision.confidence * 100
                            ).toFixed(0)}
                            %
                          </span>
                        </div>
                        <div className="text-gray-500 italic">
                          {activeState.last_decision.reason}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Node Grid */}
                  <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
                    {nodes.map((node) => {
                      const isActive = node.code === activeCode;
                      const isDetailOpen = selectedDetail === node.code;
                      return (
                        <div key={node.code} className="relative">
                          <button
                            onClick={() => selectNode(node.code)}
                            onDoubleClick={() =>
                              setSelectedDetail(
                                isDetailOpen ? null : node.code
                              )
                            }
                            disabled={switching}
                            className={cn(
                              "w-full p-2 rounded-lg border text-center transition-all text-[10px] font-mono",
                              isActive
                                ? "bg-amber-900/30 border-amber-500/60 text-amber-200 shadow-lg shadow-amber-900/20"
                                : "bg-black/30 border-gray-800 text-gray-400 hover:border-amber-800/50 hover:text-amber-300"
                            )}
                          >
                            <div className="text-lg mb-1">
                              {isActive && (
                                <CheckCircle2
                                  size={12}
                                  className="inline text-amber-400 mr-1"
                                />
                              )}
                              <span className="font-bold">{node.code}</span>
                            </div>
                            <div className="text-[9px] text-gray-500 truncate">
                              {node.name}
                            </div>
                            {/* Mini restraint bar */}
                            <div className="mt-1 h-1 bg-gray-800 rounded-full overflow-hidden">
                              <div
                                className={cn(
                                  "h-full rounded-full transition-all",
                                  node.restraint_bias >= 0.5
                                    ? "bg-blue-500"
                                    : node.restraint_bias >= 0
                                    ? "bg-cyan-600"
                                    : "bg-orange-500"
                                )}
                                style={{
                                  width: `${
                                    ((node.restraint_bias + 1) / 2) * 100
                                  }%`,
                                }}
                              />
                            </div>
                          </button>
                        </div>
                      );
                    })}
                  </div>

                  {/* Detail View (active or selected) */}
                  {(() => {
                    const detailNode =
                      nodes.find(
                        (n) => n.code === (selectedDetail || activeCode)
                      ) || null;
                    if (!detailNode) return null;
                    return (
                      <motion.div
                        key={detailNode.code}
                        initial={{ opacity: 0, y: 5 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="bg-black/30 border border-amber-900/30 rounded-lg p-3 space-y-3"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-bold text-amber-300">
                              {detailNode.code}
                            </span>
                            <span className="text-xs text-gray-400">
                              {detailNode.name}
                            </span>
                          </div>
                          <button
                            onClick={() => {
                              fetchNodes();
                              fetchActive();
                            }}
                            className="p-1 hover:bg-amber-900/20 rounded transition-colors"
                            title="Refresh"
                          >
                            <RefreshCw
                              size={12}
                              className="text-amber-600"
                            />
                          </button>
                        </div>

                        {/* Value Axes */}
                        <div className="grid grid-cols-2 gap-3 text-[10px] font-mono">
                          {/* Collective vs Individual */}
                          <div className="space-y-1">
                            <div className="flex items-center gap-1 text-gray-500">
                              <Users size={10} />
                              <span>
                                {collectiveLabel(
                                  detailNode.collective_weight
                                )}
                              </span>
                            </div>
                            <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-gradient-to-r from-purple-600 to-purple-400 rounded-full"
                                style={{
                                  width: `${
                                    detailNode.collective_weight * 100
                                  }%`,
                                }}
                              />
                            </div>
                            <div className="flex justify-between text-[8px] text-gray-600">
                              <span>Individual</span>
                              <span>Collective</span>
                            </div>
                          </div>

                          {/* Restraint Bias */}
                          <div className="space-y-1">
                            <div
                              className={cn(
                                "flex items-center gap-1",
                                restraintColor(detailNode.restraint_bias)
                              )}
                            >
                              <Shield size={10} />
                              <span>
                                {restraintLabel(detailNode.restraint_bias)}
                              </span>
                            </div>
                            <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                              <div
                                className={cn(
                                  "h-full rounded-full",
                                  detailNode.restraint_bias >= 0.5
                                    ? "bg-blue-500"
                                    : detailNode.restraint_bias >= 0
                                    ? "bg-cyan-600"
                                    : "bg-orange-500"
                                )}
                                style={{
                                  width: `${
                                    ((detailNode.restraint_bias + 1) / 2) *
                                    100
                                  }%`,
                                }}
                              />
                            </div>
                            <div className="flex justify-between text-[8px] text-gray-600">
                              <span>Action</span>
                              <span>Restraint</span>
                            </div>
                          </div>
                        </div>

                        {/* Communication Style */}
                        <div className="text-[10px] font-mono">
                          <span className="text-gray-500">COMM_STYLE:</span>{" "}
                          <span className="text-amber-300">
                            {detailNode.communication_style}
                          </span>
                        </div>

                        {/* Key Concepts */}
                        {Object.keys(detailNode.key_concepts).length > 0 && (
                          <div className="space-y-1">
                            <div className="text-[10px] font-mono text-gray-500">
                              KEY_CONCEPTS:
                            </div>
                            <div className="space-y-1">
                              {Object.entries(detailNode.key_concepts).map(
                                ([concept, desc]) => (
                                  <div
                                    key={concept}
                                    className="text-[9px] font-mono bg-black/20 rounded px-2 py-1"
                                  >
                                    <span className="text-amber-400 font-bold">
                                      {concept}
                                    </span>
                                    <span className="text-gray-500">
                                      {" "}
                                      — {desc}
                                    </span>
                                  </div>
                                )
                              )}
                            </div>
                          </div>
                        )}

                        {/* Ethical Principles */}
                        {detailNode.ethical_principles.length > 0 && (
                          <div className="space-y-1">
                            <div className="text-[10px] font-mono text-gray-500">
                              ETHICAL_PRINCIPLES:
                            </div>
                            <div className="space-y-0.5">
                              {detailNode.ethical_principles.map(
                                (principle, i) => (
                                  <div
                                    key={i}
                                    className="text-[9px] font-mono text-gray-400 pl-2 border-l border-amber-900/30"
                                  >
                                    {principle}
                                  </div>
                                )
                              )}
                            </div>
                          </div>
                        )}
                      </motion.div>
                    );
                  })()}

                  {/* Footer hint */}
                  <div className="text-[9px] font-mono text-gray-600 text-center">
                    Click a node to activate — Double-click for details —
                    Routing metadata only (no LLM modification yet)
                  </div>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
