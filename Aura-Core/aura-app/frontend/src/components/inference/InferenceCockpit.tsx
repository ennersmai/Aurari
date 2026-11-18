"use client";

/**
 * InferenceCockpit — Granular inference & VRAM management panel.
 *
 * Features:
 *  - Model stack selector (Lean / Core / Titan) + Local + SGLang toggles
 *  - Active model display per stack
 *  - Sampling sliders: Temperature, Top-P, Min-P, Freq-Penalty, Presence-Penalty
 *  - Context length slider (8k–128k) with live 3090 VRAM risk indicator
 *  - Per-layer enable/disable toggles (L1–L5)
 *  - Auto-applies changes via debounced POST /system/inference-config
 */

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Cpu, ChevronDown, ChevronUp, Zap, AlertTriangle,
  CheckCircle2, Wifi, WifiOff, Server,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useInferenceConfig } from "@/hooks/useInferenceConfig";
import {
  getVRAMRisk,
  formatContextK,
  VRAMRisk,
  InferenceConfig,
} from "@/types/inference";

// ─── Constants ────────────────────────────────────────────────────────────────

const STACK_LABELS = ["LEAN", "CORE", "TITAN"] as const;

type StackColor = { bg: string; border: string; text: string; dot: string };
const STACK_COLORS: StackColor[] = [
  { bg: "rgba(74,222,128,0.08)",   border: "rgba(74,222,128,0.3)",   text: "#4ade80",   dot: "bg-emerald-400" },
  { bg: "rgba(251,191,36,0.08)",   border: "rgba(251,191,36,0.3)",   text: "#fbbf24",   dot: "bg-amber-400"   },
  { bg: "rgba(167,139,250,0.08)",  border: "rgba(167,139,250,0.3)",  text: "#a78bfa",   dot: "bg-violet-400"  },
];

const VRAM_STYLES: Record<VRAMRisk, { label: string; color: string; bar: string }> = {
  safe:    { label: "VRAM SAFE",    color: "text-emerald-400", bar: "bg-emerald-500" },
  warning: { label: "VRAM WARN",    color: "text-amber-400",   bar: "bg-amber-500"   },
  danger:  { label: "VRAM DANGER",  color: "text-red-400",     bar: "bg-red-500"     },
};

type LayerKey = "l1" | "l2" | "l3" | "l4" | "l5";
const LAYERS: { key: LayerKey; field: keyof InferenceConfig; label: string; role: string; critical?: boolean }[] = [
  { key: "l1", field: "layer_l1_enabled", label: "L1", role: "Intent Router",   critical: false },
  { key: "l2", field: "layer_l2_enabled", label: "L2", role: "Deep Analysis",   critical: false },
  { key: "l3", field: "layer_l3_enabled", label: "L3", role: "Synthesis",       critical: true  },
  { key: "l4", field: "layer_l4_enabled", label: "L4", role: "Emotion",         critical: false },
  { key: "l5", field: "layer_l5_enabled", label: "L5", role: "Struct/JSON",     critical: false },
];

// ─── Sub-components ──────────────────────────────────────────────────────────

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  const display = format ? format(value) : value.toFixed(step < 0.1 ? 2 : step < 1 ? 2 : 0);

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] font-mono">
        <span className="text-gray-500">{label}</span>
        <span className="text-emerald-400 font-bold">{display}</span>
      </div>
      <div className="relative h-1.5 rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
        <div
          className="absolute left-0 h-full rounded-full"
          style={{ width: `${pct}%`, background: "rgba(74,222,128,0.6)" }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          style={{ WebkitAppearance: "none" }}
        />
      </div>
      <div className="flex justify-between text-[8px] text-gray-700 font-mono">
        <span>{format ? format(min) : min}</span>
        <span>{format ? format(max) : max}</span>
      </div>
    </div>
  );
}

function LayerBadge({
  label,
  role,
  model,
  enabled,
  critical,
  onToggle,
}: {
  label: string;
  role: string;
  model?: string;
  enabled: boolean;
  critical?: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className={cn(
        "flex flex-col items-center gap-0.5 p-2 rounded-lg border text-center transition-all min-w-[72px]",
        "hover:border-white/20",
        enabled
          ? "border-emerald-500/25 bg-emerald-500/5"
          : "border-white/[0.06] bg-white/[0.02] opacity-50",
      )}
      title={critical && !enabled ? "L3 is required for response generation" : undefined}
    >
      <span className={cn("text-[11px] font-mono font-bold", enabled ? "text-emerald-400" : "text-gray-600")}>
        {label}
      </span>
      <span className="text-[8px] text-gray-600">{role}</span>
      {model && (
        <span className="text-[7px] text-gray-700 truncate max-w-[64px]">
          {model.split("/")[1] || model}
        </span>
      )}
      {/* Toggle indicator */}
      <div
        className={cn(
          "mt-0.5 w-5 h-2.5 rounded-full border transition-all",
          enabled ? "border-emerald-500/40 bg-emerald-500/20" : "border-white/10 bg-white/[0.03]",
        )}
      />
    </button>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function InferenceCockpit() {
  const { config, activeModels, isLoading, isSaving, updateConfig, applyNow } = useInferenceConfig();
  const [isOpen, setIsOpen] = useState(false);

  const vramRisk = getVRAMRisk(config.context_length);
  const vramStyle = VRAM_STYLES[vramRisk];
  const activeStack = STACK_COLORS[config.model_stack_index] ?? STACK_COLORS[0];

  // ── Handlers ────────────────────────────────────────────────────────────
  const switchStack = (idx: number) => {
    applyNow({ model_stack_index: idx });
  };

  const toggleLayer = (field: keyof InferenceConfig) => {
    const current = config[field] as boolean;
    // L3 can be toggled but show a warning
    updateConfig({ [field]: !current });
  };

  // ── Panel header summary ─────────────────────────────────────────────────
  const stackLabel = STACK_LABELS[config.model_stack_index] ?? "LEAN";

  return (
    <div
      className="rounded-xl border transition-all"
      style={{ borderColor: "rgba(255,255,255,0.07)", background: "rgba(12,12,16,0.7)" }}
    >
      {/* ── Header ── */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-2.5 group"
      >
        <div className="flex items-center gap-2">
          <Cpu size={13} className="text-emerald-500/70" />
          <span className="text-[11px] font-mono font-bold tracking-wider text-emerald-400/90">
            INFERENCE_COCKPIT
          </span>

          {/* Stack badge */}
          <span
            className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold"
            style={{ background: activeStack.bg, border: `1px solid ${activeStack.border}`, color: activeStack.text }}
          >
            {stackLabel}
          </span>

          {/* Local badge */}
          {config.local_mode_enabled && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono"
              style={{ background: "rgba(167,139,250,0.1)", border: "1px solid rgba(167,139,250,0.25)", color: "#a78bfa" }}>
              <Server size={8} /> LOCAL
            </span>
          )}

          {/* SGLang badge */}
          {config.sglang_enabled && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono"
              style={{ background: "rgba(251,191,36,0.1)", border: "1px solid rgba(251,191,36,0.25)", color: "#fbbf24" }}>
              <Zap size={8} /> SGLANG
            </span>
          )}

          {/* Mini stats */}
          <span className="text-[9px] font-mono text-gray-600">
            T:{config.temperature.toFixed(1)} · {formatContextK(config.context_length)}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* VRAM risk dot */}
          <span className={cn("text-[9px] font-mono", vramStyle.color)}>{vramStyle.label}</span>
          {isSaving && <span className="text-[9px] text-amber-400/60 font-mono animate-pulse">SAVING…</span>}
          {isLoading && <span className="text-[9px] text-gray-600 font-mono">LOADING…</span>}
          {isOpen ? <ChevronUp size={14} className="text-gray-600" /> : <ChevronDown size={14} className="text-gray-600" />}
        </div>
      </button>

      {/* ── Expandable body ── */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-4 border-t border-white/[0.05] pt-3">

              {/* ── 1. Model Stack + Mode Routing ── */}
              <div className="space-y-2">
                <div className="text-[9px] font-mono text-gray-600 tracking-wider">MODEL_STACK</div>

                {/* Stack selector */}
                <div className="flex gap-1.5">
                  {STACK_LABELS.map((label, idx) => {
                    const sc = STACK_COLORS[idx];
                    const active = config.model_stack_index === idx;
                    return (
                      <button
                        key={label}
                        onClick={() => switchStack(idx)}
                        className="flex-1 py-1.5 rounded-lg text-[10px] font-mono font-bold transition-all border"
                        style={{
                          background: active ? sc.bg : "rgba(255,255,255,0.02)",
                          borderColor: active ? sc.border : "rgba(255,255,255,0.06)",
                          color: active ? sc.text : "rgba(150,150,150,0.6)",
                        }}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>

                {/* Local + SGLang toggles */}
                <div className="flex gap-1.5">
                  <button
                    onClick={() => applyNow({ local_mode_enabled: !config.local_mode_enabled })}
                    className={cn(
                      "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg border text-[10px] font-mono transition-all",
                      config.local_mode_enabled
                        ? "border-violet-500/30 bg-violet-500/10 text-violet-300"
                        : "border-white/[0.06] bg-white/[0.02] text-gray-600",
                    )}
                  >
                    {config.local_mode_enabled ? <Wifi size={10} /> : <WifiOff size={10} />}
                    LOCAL
                  </button>
                  <button
                    onClick={() => applyNow({ sglang_enabled: !config.sglang_enabled, local_mode_enabled: config.sglang_enabled ? config.local_mode_enabled : true })}
                    className={cn(
                      "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg border text-[10px] font-mono transition-all",
                      config.sglang_enabled
                        ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                        : "border-white/[0.06] bg-white/[0.02] text-gray-600",
                    )}
                    title="SGLang enables constrained output & radix-attention. Requires local mode."
                  >
                    <Zap size={10} />
                    SGLANG
                  </button>
                </div>

                {/* Active model display */}
                {activeModels && (
                  <div className="grid grid-cols-5 gap-1 mt-1">
                    {(["l1", "l2", "l3", "l4", "l5"] as LayerKey[]).map((k) => (
                      <div key={k} className="text-center">
                        <div className="text-[8px] text-gray-600 font-mono">{k.toUpperCase()}</div>
                        <div
                          className="text-[7px] font-mono truncate"
                          style={{ color: config[`layer_${k}_enabled` as keyof InferenceConfig] ? "#4ade80" : "rgba(150,150,150,0.4)" }}
                          title={activeModels[k]}
                        >
                          {(activeModels[k] || "—").split("/")[1] || activeModels[k] || "—"}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="border-t border-white/[0.04]" />

              {/* ── 2. Sampling Sliders ── */}
              <div className="space-y-3">
                <div className="text-[9px] font-mono text-gray-600 tracking-wider">SAMPLING</div>
                <SliderRow
                  label="Temperature"
                  value={config.temperature}
                  min={0} max={2} step={0.05}
                  onChange={(v) => updateConfig({ temperature: v })}
                />
                <SliderRow
                  label="Top-P"
                  value={config.top_p}
                  min={0} max={1} step={0.05}
                  onChange={(v) => updateConfig({ top_p: v })}
                />
                <SliderRow
                  label="Min-P"
                  value={config.min_p}
                  min={0} max={0.2} step={0.01}
                  onChange={(v) => updateConfig({ min_p: v })}
                />
                <div className="grid grid-cols-2 gap-3">
                  <SliderRow
                    label="Freq. Penalty"
                    value={config.frequency_penalty}
                    min={-2} max={2} step={0.1}
                    onChange={(v) => updateConfig({ frequency_penalty: v })}
                  />
                  <SliderRow
                    label="Pres. Penalty"
                    value={config.presence_penalty}
                    min={-2} max={2} step={0.1}
                    onChange={(v) => updateConfig({ presence_penalty: v })}
                  />
                </div>
                <SliderRow
                  label="Max Tokens (response)"
                  value={config.max_tokens}
                  min={256} max={8192} step={256}
                  onChange={(v) => updateConfig({ max_tokens: v })}
                  format={(v) => `${v}`}
                />
              </div>

              <div className="border-t border-white/[0.04]" />

              {/* ── 3. Context Length + VRAM Risk ── */}
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <div className="text-[9px] font-mono text-gray-600 tracking-wider">CONTEXT_WINDOW</div>
                  <div className={cn("flex items-center gap-1 text-[9px] font-mono font-bold", vramStyle.color)}>
                    {vramRisk === "safe"    && <CheckCircle2   size={10} />}
                    {vramRisk === "warning" && <AlertTriangle  size={10} />}
                    {vramRisk === "danger"  && <AlertTriangle  size={10} />}
                    {vramStyle.label}
                  </div>
                </div>

                {/* VRAM risk bar */}
                <div className="h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                  <div
                    className={cn("h-full rounded-full transition-all", vramStyle.bar)}
                    style={{ width: `${(config.context_length / 131072) * 100}%`, opacity: 0.7 }}
                  />
                </div>

                <SliderRow
                  label={`Context Length (${formatContextK(config.context_length)} tokens)`}
                  value={config.context_length}
                  min={2048} max={131072} step={4096}
                  onChange={(v) => updateConfig({ context_length: v })}
                  format={formatContextK}
                />

                {/* VRAM risk legend for 3090 */}
                <div className="flex gap-3 text-[8px] font-mono">
                  <span className="text-emerald-600">■ &lt;16k safe</span>
                  <span className="text-amber-600">■ 16–48k risky 24B+</span>
                  <span className="text-red-800">■ &gt;48k critical</span>
                </div>
              </div>

              <div className="border-t border-white/[0.04]" />

              {/* ── 4. Layer Toggles ── */}
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <div className="text-[9px] font-mono text-gray-600 tracking-wider">COGNITIVE_LAYERS</div>
                  <div className="text-[8px] text-gray-700 font-mono">click to toggle</div>
                </div>
                <div className="flex gap-1.5 flex-wrap">
                  {LAYERS.map(({ key, field, label, role, critical }) => (
                    <LayerBadge
                      key={key}
                      label={label}
                      role={role}
                      model={activeModels?.[key]}
                      enabled={config[field] as boolean}
                      critical={critical}
                      onToggle={() => toggleLayer(field)}
                    />
                  ))}
                </div>

                {/* Warning when L3 is off */}
                {!config.layer_l3_enabled && (
                  <div className="flex items-center gap-1.5 text-[9px] font-mono text-amber-400/80 bg-amber-500/5 rounded-lg p-2 border border-amber-500/15">
                    <AlertTriangle size={10} />
                    L3 disabled — L1 cold-start reply used as fallback (very short).
                  </div>
                )}

                {/* Info when running L3-only */}
                {!config.layer_l1_enabled && !config.layer_l2_enabled && config.layer_l3_enabled && (
                  <div className="flex items-center gap-1.5 text-[9px] font-mono text-violet-400/80 bg-violet-500/5 rounded-lg p-2 border border-violet-500/15">
                    <Cpu size={10} />
                    L3-only mode — single model handles all synthesis. Ideal for a 24B local.
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
