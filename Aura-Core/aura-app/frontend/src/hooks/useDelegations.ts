/**
 * useDelegations: polls the delegation list (5 s) and the selected task (2 s while running).
 * The timing logic lives in createDelegationPoller so it can be tested with fake timers.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { delegationApi, isRunningState, type Delegation, type DelegationApi } from '@/services/delegationService';

export const LIST_POLL_MS = 5000;
export const TASK_POLL_MS = 2000;

export interface PollerDeps {
  api: Pick<DelegationApi, 'list' | 'get'>;
  onList: (items: Delegation[], paused: boolean) => void;
  onTask: (task: Delegation) => void;
  onError?: (e: unknown) => void;
}

export function createDelegationPoller(deps: PollerDeps) {
  let listTimer: ReturnType<typeof setInterval> | null = null;
  let taskTimer: ReturnType<typeof setInterval> | null = null;
  let selected: string | null = null;
  let stopped = false;

  const stopTask = () => { if (taskTimer) { clearInterval(taskTimer); taskTimer = null; } };

  const pollList = async () => {
    try {
      const r = await deps.api.list();
      if (!stopped) deps.onList(r.delegations, !!r.paused);
    } catch (e) { deps.onError?.(e); }
  };
  const pollTask = async () => {
    const id = selected;
    if (!id) return;
    try {
      const t = await deps.api.get(id);
      if (stopped || selected !== id) return;
      deps.onTask(t);
      if (!isRunningState(t.state)) stopTask(); // closed (or not running): stop polling it
    } catch (e) { deps.onError?.(e); }
  };

  return {
    start() {
      stopped = false;
      void pollList();
      listTimer = setInterval(pollList, LIST_POLL_MS);
    },
    select(id: string | null, state?: string) {
      stopTask();
      selected = id;
      if (!id) return;
      void pollTask();
      if (state === undefined || isRunningState(state)) taskTimer = setInterval(pollTask, TASK_POLL_MS);
    },
    refresh: pollList,
    stop() {
      stopped = true;
      if (listTimer) clearInterval(listTimer);
      listTimer = null;
      stopTask();
    },
  };
}

export function useDelegations(selectedId: string | null) {
  const [items, setItems] = useState<Delegation[]>([]);
  const [paused, setPaused] = useState(false);
  const [task, setTask] = useState<Delegation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const poller = useRef<ReturnType<typeof createDelegationPoller> | null>(null);
  const itemsRef = useRef<Delegation[]>([]);

  useEffect(() => {
    const p = createDelegationPoller({
      api: delegationApi,
      onList: (list, pz) => { itemsRef.current = list; setItems(list); setPaused(pz); setError(null); },
      onTask: setTask,
      onError: (e) => setError(e instanceof Error ? e.message : String(e)),
    });
    poller.current = p;
    p.start();
    return () => { p.stop(); poller.current = null; };
  }, []);

  useEffect(() => {
    setTask(null);
    const known = itemsRef.current.find((i) => i.task_id === selectedId);
    poller.current?.select(selectedId, known?.state);
  }, [selectedId]);

  const refresh = useCallback(() => poller.current?.refresh(), []);
  return { items, paused, task, error, refresh, setPaused };
}
