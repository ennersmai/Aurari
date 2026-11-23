import React from 'react';
import type { AgendaItem } from '@/services/auraApiService';

/** Agenda items with acknowledge and dismiss (B1-07). */
export function AgendaPanel({ items, onAck, onDismiss }: {
  items: AgendaItem[]; onAck: (id: string) => void; onDismiss: (id: string) => void;
}) {
  if (items.length === 0) {
    return <div data-testid="agenda-empty" className="text-xs" style={{ opacity: 0.6 }}>Nothing on the agenda.</div>;
  }
  return (
    <ul data-testid="agenda-list" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
      {items.map((i) => (
        <li key={i.id} className="glass-panel-sm" style={{ padding: 8 }}>
          <div className="text-xs" style={{ opacity: 0.6 }}>
            {i.kind}{i.due_at ? ` · due ${i.due_at}` : ''}{i.state === 'delivered' ? ' · delivered' : ''}
          </div>
          <div className="text-sm">{i.content}</div>
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button type="button" className="glass-btn text-xs" onClick={() => onAck(i.id)}>Acknowledge</button>
            <button type="button" className="glass-btn text-xs" onClick={() => onDismiss(i.id)}>Dismiss</button>
          </div>
        </li>
      ))}
    </ul>
  );
}
