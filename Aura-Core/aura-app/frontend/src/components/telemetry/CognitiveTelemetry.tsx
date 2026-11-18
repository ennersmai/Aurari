"use client";

/**
 * CognitiveTelemetry — Live L1 / L2 / L3 trace feed
 *
 * PERFORMANCE CONTRACT
 * ─────────────────────────────────────────────────────────────────────────
 * • WebSocket to /v1/stream/traces is created ONLY when the modal is open
 *   (component is mounted with open=true).
 * • When the modal is closed the socket is immediately severed and the
 *   component unmounts, releasing all memory — zero DOM cost while closed.
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Box, Typography, IconButton, Tooltip } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep';
import { API_BASE_URL } from '@/config';

// ── Types ──────────────────────────────────────────────────────────────────

interface TraceEvent {
  type?: string;         // "ping" | undefined
  layer?: 'L1' | 'L2' | 'L3';
  event?: string;
  ts?: string;
  intent?: string;
  model?: string;
  confidence?: number;
  round?: number;
  patterns?: number;
  insights?: number;
  has_critique?: boolean;
  response_len?: number;
  mode?: string;
  [key: string]: unknown;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

// ── Layer palette ───────────────────────────────────────────────────────────

const LAYER_COLOR: Record<string, string> = {
  L1: '#22d3ee',   // cyan  — routing decisions
  L2: '#a78bfa',   // violet — internal analysis
  L3: '#4ade80',   // green  — synthesis / response
};

const MAX_EVENTS = 200;

// ── Helper: build a one-line summary of a trace event ──────────────────────

function summarise(t: TraceEvent): React.ReactNode {
  if (!t.event) return null;
  const parts: React.ReactNode[] = [
    <span key="ev" style={{ color: 'rgba(255,255,255,0.80)' }}>{t.event}</span>,
  ];
  if (t.intent)
    parts.push(<span key="intent" style={{ color: '#f59e0b', marginLeft: 4 }}>→ {t.intent}</span>);
  if (t.confidence !== undefined)
    parts.push(<span key="conf" style={{ color: 'rgba(255,255,255,0.3)', marginLeft: 4 }}>({(t.confidence * 100).toFixed(0)}%)</span>);
  if (t.model)
    parts.push(<span key="model" style={{ color: 'rgba(255,255,255,0.25)', marginLeft: 4 }}>[{String(t.model).split('/').pop()}]</span>);
  if (t.round !== undefined)
    parts.push(<span key="round" style={{ color: 'rgba(255,255,255,0.25)', marginLeft: 4 }}>round {t.round}</span>);
  if (t.patterns !== undefined)
    parts.push(<span key="pats" style={{ color: '#a78bfa', marginLeft: 4 }}>{t.patterns} patterns</span>);
  if (t.response_len !== undefined)
    parts.push(<span key="rlen" style={{ color: 'rgba(255,255,255,0.25)', marginLeft: 4 }}>{t.response_len}c</span>);
  return <>{parts}</>;
}

function fmtTs(iso?: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour12: false });
  } catch {
    return '';
  }
}

// ── Component ───────────────────────────────────────────────────────────────

export default function CognitiveTelemetry({ open, onClose }: Props) {
  const [traces, setTraces] = useState<TraceEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Build the WebSocket URL from the REST base URL
  const wsUrl = API_BASE_URL.replace(/^http/, 'ws') + '/v1/stream/traces';

  const connect = useCallback(() => {
    if (wsRef.current) return;            // already connecting
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => { setConnected(false); wsRef.current = null; };
    ws.onerror = () => { setConnected(false); };
    ws.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as TraceEvent;
        if (evt.type === 'ping') return;  // heartbeat — ignore
        setTraces(prev => {
          const next = [...prev, evt];
          return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
        });
      } catch { /* malformed frame — skip */ }
    };
    wsRef.current = ws;
  }, [wsUrl]);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  // Mount WebSocket only when open; sever on close / unmount
  useEffect(() => {
    if (open) {
      setTraces([]);
      connect();
    } else {
      disconnect();
    }
    return () => disconnect();
  }, [open, connect, disconnect]);

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [traces]);

  if (!open) return null;

  return (
    <Box
      sx={{
        position: 'fixed',
        top: 68,
        right: 16,
        width: { xs: 'calc(100vw - 32px)', sm: 440 },
        maxHeight: 'calc(100vh - 90px)',
        zIndex: 1500,
        display: 'flex',
        flexDirection: 'column',
        background: 'rgba(8, 8, 14, 0.94)',
        backdropFilter: 'blur(28px) saturate(180%)',
        WebkitBackdropFilter: 'blur(28px) saturate(180%)',
        border: '1px solid rgba(34, 211, 238, 0.14)',
        borderRadius: '14px',
        boxShadow: '0 24px 64px rgba(0,0,0,0.6), 0 0 0 1px rgba(34,211,238,0.04)',
        overflow: 'hidden',
        '@keyframes telemetryPulse': {
          '0%, 100%': { opacity: 1 },
          '50%': { opacity: 0.4 },
        },
      }}
    >
      {/* ─── Header ────────────────────────────────────────────────── */}
      <Box
        sx={{
          px: 2,
          py: 1.25,
          borderBottom: '1px solid rgba(255,255,255,0.04)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'rgba(34,211,238,0.03)',
          flexShrink: 0,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {/* Live indicator */}
          <Box
            sx={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              bgcolor: connected ? '#22d3ee' : '#6b7280',
              animation: connected ? 'telemetryPulse 2s ease-in-out infinite' : 'none',
              flexShrink: 0,
            }}
          />
          <Typography
            sx={{
              fontFamily: 'monospace',
              fontSize: '0.68rem',
              color: '#22d3ee',
              letterSpacing: '0.12em',
              fontWeight: 700,
            }}
          >
            COGNITIVE TELEMETRY
          </Typography>
          <Typography
            sx={{
              fontFamily: 'monospace',
              fontSize: '0.6rem',
              color: 'rgba(255,255,255,0.2)',
              letterSpacing: '0.05em',
            }}
          >
            {connected ? 'LIVE' : 'OFFLINE'}
          </Typography>
        </Box>

        <Box sx={{ display: 'flex', gap: 0.25 }}>
          <Tooltip title="Clear feed">
            <IconButton
              onClick={() => setTraces([])}
              size="small"
              sx={{ color: 'rgba(255,255,255,0.3)', p: 0.5, '&:hover': { color: 'rgba(255,255,255,0.6)' } }}
            >
              <DeleteSweepIcon sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
          <IconButton
            onClick={onClose}
            size="small"
            sx={{ color: 'rgba(255,255,255,0.3)', p: 0.5, '&:hover': { color: 'rgba(255,255,255,0.7)' } }}
          >
            <CloseIcon sx={{ fontSize: 15 }} />
          </IconButton>
        </Box>
      </Box>

      {/* ─── Layer legend ──────────────────────────────────────────── */}
      <Box
        sx={{
          px: 2,
          py: 0.75,
          display: 'flex',
          gap: 2,
          borderBottom: '1px solid rgba(255,255,255,0.03)',
          flexShrink: 0,
        }}
      >
        {(['L1', 'L2', 'L3'] as const).map((l) => (
          <Box key={l} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 6, height: 6, borderRadius: 1, bgcolor: LAYER_COLOR[l] }} />
            <Typography sx={{ fontFamily: 'monospace', fontSize: '0.6rem', color: 'rgba(255,255,255,0.35)' }}>
              {l === 'L1' ? 'L1 Route' : l === 'L2' ? 'L2 Cognition' : 'L3 Synthesis'}
            </Typography>
          </Box>
        ))}
      </Box>

      {/* ─── Trace feed ────────────────────────────────────────────── */}
      <Box
        ref={scrollRef}
        sx={{
          flexGrow: 1,
          overflowY: 'auto',
          px: 1.5,
          py: 1,
          fontFamily: 'monospace',
          fontSize: '0.67rem',
          lineHeight: 1.75,
          '&::-webkit-scrollbar': { width: 3 },
          '&::-webkit-scrollbar-thumb': { background: 'rgba(255,255,255,0.06)', borderRadius: 2 },
          scrollbarWidth: 'thin',
          scrollbarColor: 'rgba(255,255,255,0.06) transparent',
        }}
      >
        {traces.length === 0 ? (
          <Typography
            sx={{
              color: 'rgba(255,255,255,0.18)',
              fontFamily: 'monospace',
              fontSize: '0.67rem',
              p: 1,
              textAlign: 'center',
              mt: 2,
            }}
          >
            Waiting for cognitive events…
            <br />
            <span style={{ fontSize: '0.6rem', opacity: 0.6 }}>
              Send a message to see L1 / L2 / L3 traces appear here.
            </span>
          </Typography>
        ) : (
          traces.map((t, i) => {
            const layer = t.layer ?? 'L1';
            const color = LAYER_COLOR[layer] ?? '#94a3b8';
            return (
              <Box
                key={i}
                sx={{
                  display: 'flex',
                  gap: 0.75,
                  alignItems: 'baseline',
                  mb: 0.15,
                  '&:hover': { background: 'rgba(255,255,255,0.02)', borderRadius: '4px' },
                  px: 0.5,
                }}
              >
                {/* Layer badge */}
                <Box
                  component="span"
                  sx={{
                    color,
                    fontWeight: 700,
                    flexShrink: 0,
                    fontSize: '0.62rem',
                    letterSpacing: '0.05em',
                    minWidth: 20,
                  }}
                >
                  {layer}
                </Box>
                {/* Timestamp */}
                <Box
                  component="span"
                  sx={{ color: 'rgba(255,255,255,0.2)', flexShrink: 0, fontSize: '0.6rem' }}
                >
                  {fmtTs(t.ts)}
                </Box>
                {/* Summary */}
                <Box component="span" sx={{ wordBreak: 'break-all', flex: 1, minWidth: 0 }}>
                  {summarise(t)}
                </Box>
              </Box>
            );
          })
        )}
      </Box>

      {/* ─── Footer: event count ───────────────────────────────────── */}
      <Box
        sx={{
          px: 2,
          py: 0.5,
          borderTop: '1px solid rgba(255,255,255,0.03)',
          display: 'flex',
          justifyContent: 'flex-end',
          flexShrink: 0,
        }}
      >
        <Typography sx={{ fontFamily: 'monospace', fontSize: '0.58rem', color: 'rgba(255,255,255,0.15)' }}>
          {traces.length} / {MAX_EVENTS} events
        </Typography>
      </Box>
    </Box>
  );
}
