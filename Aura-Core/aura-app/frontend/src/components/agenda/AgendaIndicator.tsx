import React from 'react';

/** Quiet indicator (B1-07): a small badge with the pending count; nothing loud when there is none. */
export function AgendaIndicator({ count, killed = false, onClick }: { count: number; killed?: boolean; onClick?: () => void }) {
  const label = killed ? 'Autonomy stopped' : count > 0 ? `${count} pending agenda item${count === 1 ? '' : 's'}` : 'Agenda';
  return (
    <button
      type="button"
      className="glass-btn text-xs"
      data-testid="agenda-indicator"
      aria-label={label}
      title={label}
      onClick={onClick}
      style={{ padding: '2px 10px', borderRadius: 999, color: killed ? '#f87171' : undefined }}
    >
      {killed ? 'Stopped' : 'Agenda'}
      {count > 0 && (
        <span
          data-testid="agenda-badge"
          style={{ marginLeft: 6, minWidth: 16, padding: '0 5px', borderRadius: 999, background: 'rgba(192,156,88,0.35)', fontSize: 10 }}
        >
          {count}
        </span>
      )}
    </button>
  );
}
