import React from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { accentVar, entranceProps, type Accent } from './accent';
import { Sparkline } from './Sparkline';

export interface StatTileProps {
  label: string;
  value: string | number;
  unit?: string;
  /** Change since the previous period, in percent; the sign sets the arrow. */
  delta?: number;
  accent?: Accent;
  spark?: number[];
}

export function StatTile({ label, value, unit, delta, accent, spark }: StatTileProps) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className="glass-panel"
      data-accent={accent}
      style={{ padding: 'var(--space-5)', minWidth: 160 }}
      {...entranceProps(reduced)}
    >
      <div style={{ position: 'relative' }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          {label}
        </div>
        <div className="tabular-nums" style={{ marginTop: 'var(--space-2)', display: 'flex', alignItems: 'baseline', gap: 'var(--space-2)' }}>
          <span style={{ fontSize: 32, fontWeight: 600, lineHeight: 1.1, color: 'var(--text-bright)',
            textShadow: `0 0 18px ${accentVar(accent)}` }}>
            {value}
          </span>
          {unit && <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{unit}</span>}
        </div>
        <div style={{ marginTop: 'var(--space-3)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)' }}>
          {delta !== undefined ? (
            <span className="tabular-nums" style={{ fontSize: 12, color: accentVar(accent) }}>
              {delta > 0 ? '▲' : delta < 0 ? '▼' : '•'} {Math.abs(delta)}%
            </span>
          ) : <span />}
          {spark && <Sparkline data={spark} accent={accent} />}
        </div>
      </div>
    </motion.div>
  );
}
