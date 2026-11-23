import React from 'react';
import type { DelegationBlocker, DelegationStep } from '@/services/delegationService';

export const stepKind = (s: DelegationStep): string => {
  const k = String(s.step_type ?? s.type ?? 'step');
  return k === 'status' ? 'heartbeat' : k; // G4-02 writes heartbeats as step_type "status"
};

export function emotionTag(e: DelegationStep['emotion']): string | null {
  if (!e) return null;
  const top = Object.entries(e).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k]) => k);
  return top.length ? top.join(', ') : null;
}

const STYLE: Record<string, { color: string; label: string }> = {
  guidance: { color: '#a78bfa', label: 'You' },
  heartbeat: { color: '#6b7280', label: 'heartbeat' },
  blocker: { color: '#f87171', label: 'blocker' },
};

export function blockerText(b: DelegationBlocker | string | null | undefined): { reason: string; suggestion?: string; kind?: string } | null {
  if (!b) return null;
  if (typeof b === 'string') return { reason: b };
  return { reason: String(b.reason ?? JSON.stringify(b)), suggestion: b.suggestion ?? undefined, kind: b.kind };
}

export function StepLog({ steps, blocker }: { steps: DelegationStep[]; blocker?: DelegationBlocker | string | null }) {
  const bl = blockerText(blocker);
  return (
    <div className="glass-panel p-3 flex flex-col gap-1 font-mono text-xs" data-testid="step-log">
      {steps.map((s, i) => {
        const kind = stepKind(s);
        const st = STYLE[kind];
        const tag = emotionTag(s.emotion);
        return (
          <div key={s.step_number ?? i} className={`step step-${kind}`} data-kind={kind}
            style={{ color: st?.color, opacity: kind === 'heartbeat' ? 0.6 : 1 }}>
            {st && <span className="step-label">[{st.label}] </span>}
            {s.description ?? s.summary ?? ''}
            {tag && <span className="emotion-tag glass-chip ml-2 text-[10px]">{tag}</span>}
          </div>
        );
      })}
      {bl && (
        <div className="step step-blocker blocker" data-kind="blocker" style={{ color: STYLE.blocker.color }}>
          <strong>[blocker{bl.kind ? `: ${bl.kind}` : ''}]</strong> {bl.reason}
          {bl.suggestion && <div className="blocker-suggestion">Suggestion: {bl.suggestion}</div>}
        </div>
      )}
    </div>
  );
}
