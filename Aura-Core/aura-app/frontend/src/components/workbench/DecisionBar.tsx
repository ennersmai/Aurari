import React from 'react';
import type { PendingDecision } from '@/services/delegationService';

export function DecisionBar({ decisions, onAnswer }: {
  decisions: PendingDecision[]; onAnswer: (id: string, allow: boolean) => void;
}) {
  if (decisions.length === 0) return null;
  return (
    <div className="glass-panel p-3 flex flex-col gap-2" data-testid="decision-bar">
      {decisions.map((d) => (
        <div key={d.id} className="flex items-center gap-2 text-xs">
          <span className="flex-1 truncate">{String(d.title ?? d.description ?? d.tool ?? d.id)}</span>
          <button className="glass-btn glass-btn-accent text-xs" onClick={() => onAnswer(d.id, true)}>Approve</button>
          <button className="glass-btn text-xs" onClick={() => onAnswer(d.id, false)}>Deny</button>
        </div>
      ))}
    </div>
  );
}
