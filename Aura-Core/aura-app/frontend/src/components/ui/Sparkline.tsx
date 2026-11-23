import React from 'react';
import { accentVar, type Accent } from './accent';

export interface SparklineProps {
  data: number[];
  accent?: Accent;
  width?: number;
  height?: number;
}

/** Tiny inline glow line (plain SVG, cheap enough to sit inside tiles). */
export function Sparkline({ data, accent, width = 96, height = 28 }: SparklineProps) {
  const color = accentVar(accent);
  if (!data || data.length < 2) return <svg width={width} height={height} aria-hidden />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pad = 2;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (width - pad * 2);
    const y = pad + (1 - (v - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="trend" data-accent={accent}>
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ filter: `drop-shadow(0 0 3px ${color})` }}
      />
    </svg>
  );
}
