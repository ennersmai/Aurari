import React from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { accentVar, entranceProps, type Accent } from './accent';

export interface GlassCardProps {
  title?: string;
  accent?: Accent;
  children?: React.ReactNode;
  className?: string;
}

export function GlassCard({ title, accent, children, className = '' }: GlassCardProps) {
  const reduced = useReducedMotion();
  const style = { '--card-accent': accentVar(accent), padding: 'var(--space-5)' } as React.CSSProperties;
  return (
    <motion.section
      className={`glass-panel ${className}`.trim()}
      data-accent={accent}
      style={style}
      {...entranceProps(reduced)}
    >
      {accent && (
        <span
          aria-hidden
          style={{
            position: 'absolute', top: 0, left: 'var(--space-5)', right: 'var(--space-5)', height: 1,
            background: 'linear-gradient(90deg, transparent, var(--card-accent), transparent)', opacity: 0.6,
          }}
        />
      )}
      {title && (
        <h3 style={{ margin: '0 0 var(--space-4)', fontSize: 12, fontWeight: 500, letterSpacing: '0.08em',
          textTransform: 'uppercase', color: 'var(--text-muted)', position: 'relative' }}>
          {title}
        </h3>
      )}
      <div style={{ position: 'relative' }}>{children}</div>
    </motion.section>
  );
}
