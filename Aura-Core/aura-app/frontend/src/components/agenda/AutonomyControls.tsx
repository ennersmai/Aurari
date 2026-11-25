import React from 'react';
import type { AutonomyLevel, AutonomyState } from '@/services/auraApiService';
import { AGENDA_KINDS, AUTONOMY_LEVELS, budgetSummary, cappedNote, confirmKill, mutedKinds } from './agendaState';

/** Owner controls (B1-07, P2-33): autonomy slider 0-3 with today's budget, per-kind mutes,
 * and a separated kill switch with a confirm. */
export function AutonomyControls({ state, onLevel, onMute, onUnmute, onKill, onResume, confirmFn }: {
  state: AutonomyState | null;
  onLevel: (l: AutonomyLevel) => void;
  onMute: (kind: string) => void;
  onUnmute: (kind: string) => void;
  onKill: () => void;
  onResume: () => void;
  confirmFn?: (m: string) => boolean;
}) {
  if (!state) return <div className="text-xs" style={{ opacity: 0.6 }}>Controls unavailable.</div>;
  const muted = mutedKinds(state);
  const kinds = Array.from(new Set([...AGENDA_KINDS, ...state.muted_kinds]));
  return (
    <div data-testid="autonomy-controls" style={{ display: 'grid', gap: 10 }}>
      {state.killed && (
        <div data-testid="killed-banner" role="alert" style={{ padding: 8, borderRadius: 8, border: '1px solid #f87171', color: '#f87171' }}>
          <strong>KILLED</strong>
          <span className="text-xs"> Aura is not acting on her own{state.killed_at ? ` (since ${state.killed_at})` : ''}.</span>
          <div style={{ marginTop: 6 }}>
            <button type="button" className="glass-btn text-xs" onClick={onResume}>Resume autonomy</button>
          </div>
        </div>
      )}
      <div>
        <div className="text-xs" style={{ opacity: 0.6 }}>Autonomy level</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 4 }} role="group" aria-label="Autonomy level">
          {AUTONOMY_LEVELS.map(({ level, name, may }) => (
            <button
              key={level} type="button" aria-pressed={state.level === level} title={`${name}: ${may}`}
              data-testid={`autonomy-level-${level}`}
              className={state.level === level ? 'glass-btn glass-btn-accent text-xs' : 'glass-btn text-xs'}
              onClick={() => onLevel(level as AutonomyLevel)}
            >{`${level} ${name}`}</button>
          ))}
        </div>
        <div className="text-xs" style={{ opacity: 0.6, marginTop: 4 }} data-testid="autonomy-level-may">
          {AUTONOMY_LEVELS[state.level]?.may ?? ''}
        </div>
        {cappedNote(state) && <div className="text-xs" data-testid="autonomy-capped" style={{ marginTop: 4 }}>{cappedNote(state)}</div>}
        {budgetSummary(state) && <div className="text-xs" data-testid="autonomy-budget" style={{ opacity: 0.6, marginTop: 4 }}>Today: {budgetSummary(state)}</div>}
        {state.quiet_hours?.active && <div className="text-xs" style={{ opacity: 0.6, marginTop: 4 }}>Quiet hours are active.</div>}
      </div>
      <div>
        <div className="text-xs" style={{ opacity: 0.6 }}>Mute by kind</div>
        {kinds.map((k) => (
          <label key={k} className="text-xs" style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
            <input type="checkbox" checked={muted.has(k)} onChange={(e) => (e.target.checked ? onMute(k) : onUnmute(k))} />
            Mute {k}
          </label>
        ))}
      </div>
      {!state.killed && (
        <div style={{ borderTop: '1px solid rgba(248,113,113,0.3)', paddingTop: 10, marginTop: 6 }}>
          <button
            type="button" className="glass-btn text-xs" data-testid="kill-button"
            style={{ color: '#f87171', borderColor: '#f87171' }}
            onClick={() => confirmKill(onKill, confirmFn)}
          >Kill switch</button>
        </div>
      )}
    </div>
  );
}
