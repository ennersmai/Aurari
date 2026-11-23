import React from 'react';
import { isClosedState, type Delegation } from '@/services/delegationService';

export type TaskFilter = 'all' | 'running' | 'closed';

export const stateColor = (s: string) =>
  s === 'running' ? '#34d399' : s === 'waiting_approval' ? '#fbbf24' : s === 'completed' ? '#60a5fa' : isClosedState(s) ? '#f87171' : '#9ca3af';

export function filterTasks(items: Delegation[], f: TaskFilter) {
  if (f === 'running') return items.filter((i) => !isClosedState(i.state));
  if (f === 'closed') return items.filter((i) => isClosedState(i.state));
  return items;
}

export function TaskList({ items, selectedId, filter, onFilter, onSelect }: {
  items: Delegation[]; selectedId: string | null; filter: TaskFilter;
  onFilter: (f: TaskFilter) => void; onSelect: (id: string) => void;
}) {
  const shown = filterTasks(items, filter);
  return (
    <div className="glass-panel p-3 flex flex-col gap-2" data-testid="task-list">
      <div className="flex gap-1">
        {(['all', 'running', 'closed'] as TaskFilter[]).map((f) => (
          <button key={f} className={f === filter ? 'glass-chip glass-chip-active' : 'glass-chip'} onClick={() => onFilter(f)}>{f}</button>
        ))}
      </div>
      {shown.length === 0 && <div className="text-xs text-gray-500">No delegated tasks.</div>}
      {shown.map((t) => (
        <button key={t.task_id} onClick={() => onSelect(t.task_id)}
          className={`glass-panel-sm text-left p-2 ${t.task_id === selectedId ? 'glass-chip-active' : ''}`}>
          <span className="state-badge text-[10px] font-mono uppercase" style={{ color: stateColor(t.state) }}>{t.state}</span>
          <div className="text-xs truncate">{t.brief}</div>
        </button>
      ))}
    </div>
  );
}
