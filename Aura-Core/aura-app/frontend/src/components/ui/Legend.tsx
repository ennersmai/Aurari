import React from 'react';
import { accentVar, type Accent } from './accent';

export interface LegendItem { label: string; accent: Accent }

export function Legend({ items }: { items: LegendItem[] }) {
  return (
    <ul style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-4)', listStyle: 'none', margin: 0, padding: 0 }}>
      {items.map((it) => (
        <li key={it.label} data-accent={it.accent}
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 12, color: 'var(--text-muted)' }}>
          <span aria-hidden style={{ width: 8, height: 8, borderRadius: '50%', background: accentVar(it.accent),
            boxShadow: `0 0 8px ${accentVar(it.accent)}` }} />
          {it.label}
        </li>
      ))}
    </ul>
  );
}
