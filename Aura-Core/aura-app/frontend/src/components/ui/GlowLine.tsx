import React from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { accentVar, entranceProps, type Series } from './accent';

export interface GlowLineProps {
  data: Array<Record<string, number | string>>;
  xKey?: string;
  series: Series[];
  height?: number;
}

const AXIS = { fill: 'var(--text-muted)', fontSize: 11 };

export function GlowLine({ data, xKey = 'x', series, height = 220 }: GlowLineProps) {
  const reduced = useReducedMotion();
  const uid = React.useId().replace(/:/g, '');
  return (
    <motion.div style={{ width: '100%', height }} data-chart="glow-line" {...entranceProps(reduced)}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <defs>
            {series.map((s) => (
              <linearGradient key={s.key} id={`${uid}-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={accentVar(s.accent)} stopOpacity={0.35} />
                <stop offset="100%" stopColor={accentVar(s.accent)} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <XAxis dataKey={xKey} tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44} />
          <Tooltip
            cursor={{ stroke: 'rgba(255,255,255,0.15)' }}
            contentStyle={{ background: 'rgba(12,14,20,0.9)', border: '1px solid var(--glass-stroke)',
              borderRadius: 10, color: 'var(--text-bright)', fontSize: 12 }}
            labelStyle={{ color: 'var(--text-muted)' }}
          />
          {series.map((s) => (
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label ?? s.key}
              stroke={accentVar(s.accent)}
              strokeWidth={1.75}
              fill={`url(#${uid}-${s.key})`}
              dot={false}
              activeDot={{ r: 3 }}
              isAnimationActive={!reduced}
              style={{ filter: `drop-shadow(0 0 4px ${accentVar(s.accent)})` }}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </motion.div>
  );
}
