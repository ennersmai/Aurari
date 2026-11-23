import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { agendaApi, autonomyApi, type AgendaItem, type AutonomyLevel, type AutonomyState } from '@/services/auraApiService';
import type { AuraEnvelope } from '@/services/auraChannel';
import { applyAgendaUpdate, pendingCount, resolveAgendaItem } from './agendaState';
import { AgendaIndicator } from './AgendaIndicator';
import { AgendaPanel } from './AgendaPanel';
import { AutonomyControls } from './AutonomyControls';

/** Agenda and autonomy state kept in sync from the channel (`agenda_update`, `autonomy_state`). */
export function useAgenda() {
  const [items, setItems] = useState<AgendaItem[]>([]);
  const [state, setState] = useState<AutonomyState | null>(null);

  useEffect(() => {
    let alive = true;
    agendaApi.list().then((i) => { if (alive) setItems(i); }).catch(() => {});
    autonomyApi.get().then((s) => { if (alive) setState(s); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const handlers = useMemo(() => ({
    agenda_update: (ev: AuraEnvelope) => {
      if (ev.payload?.id) setItems((cur) => applyAgendaUpdate(cur, ev.payload));
      else agendaApi.list().then(setItems).catch(() => {}); // e.g. {reason: 'expired'}
    },
    autonomy_state: (ev: AuraEnvelope) => setState(ev.payload as AutonomyState),
  }), []);

  const resolve = useCallback((action: 'ack' | 'dismiss', id: string) => {
    setItems((cur) => {
      resolveAgendaItem(action, id, cur, agendaApi).then(setItems).catch(() => {});
      return cur;
    });
  }, []);
  const run = useCallback((p: Promise<AutonomyState>) => { p.then(setState).catch(() => {}); }, []);
  const actions = useMemo(() => ({
    ack: (id: string) => resolve('ack', id),
    dismiss: (id: string) => resolve('dismiss', id),
    level: (l: AutonomyLevel) => run(autonomyApi.setLevel(l)),
    mute: (k: string) => run(autonomyApi.mute(k)),
    unmute: (k: string) => run(autonomyApi.unmute(k)),
    kill: () => run(autonomyApi.kill()),
    resume: () => run(autonomyApi.resume()),
  }), [resolve, run]);

  return { items, state, handlers, actions };
}

/** Indicator in the chat header; opens a small panel with the agenda and the owner controls. */
export function AgendaDrawer({ agenda }: { agenda: ReturnType<typeof useAgenda> }) {
  const [open, setOpen] = useState(false);
  const { items, state, actions } = agenda;
  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <AgendaIndicator count={pendingCount(items)} killed={!!state?.killed} onClick={() => setOpen((o) => !o)} />
      {open && (
        <div
          className="glass-panel" data-testid="agenda-drawer" role="dialog" aria-label="Agenda and autonomy"
          style={{ position: 'absolute', top: '120%', left: 0, width: 320, maxHeight: '70vh', overflowY: 'auto', padding: 12, zIndex: 1400, display: 'grid', gap: 14 }}
        >
          <AgendaPanel items={items} onAck={actions.ack} onDismiss={actions.dismiss} />
          <AutonomyControls
            state={state} onLevel={actions.level} onMute={actions.mute} onUnmute={actions.unmute}
            onKill={actions.kill} onResume={actions.resume}
          />
        </div>
      )}
    </span>
  );
}
