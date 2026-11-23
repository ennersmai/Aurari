import React, { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { useDelegations } from '@/hooks/useDelegations';
import { delegationApi, isRunningState, type DelegationDiff, type PendingDecision } from '@/services/delegationService';
import { TaskList, type TaskFilter } from '@/components/workbench/TaskList';
import { StepLog } from '@/components/workbench/StepLog';
import { DiffView } from '@/components/workbench/DiffView';
import { DecisionBar } from '@/components/workbench/DecisionBar';
import { GuidanceBox } from '@/components/workbench/GuidanceBox';
import { BulkControls } from '@/components/workbench/BulkControls';

export default function WorkbenchPage() {
  const router = useRouter();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<TaskFilter>('all');
  const { items, paused, task, error, refresh, setPaused } = useDelegations(selectedId);
  const [decisions, setDecisions] = useState<PendingDecision[]>([]);
  const [diff, setDiff] = useState<DelegationDiff | null>(null);
  const [ocUrl, setOcUrl] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const taskId = task?.task_id;
  const pendingKey = task?.pending_decision_ids.join(',') ?? '';
  const running = !!task && isRunningState(task.state);

  useEffect(() => {
    if (!taskId || !pendingKey) { setDecisions([]); return; }
    const ids = pendingKey.split(',');
    let alive = true;
    delegationApi.pendingDecisions()
      .then((all) => { if (alive) setDecisions(all.filter((d) => ids.includes(d.id))); })
      .catch(() => {});
    return () => { alive = false; };
  }, [taskId, pendingKey]);

  // Refetch the diff when the task changes or its state flips (running -> closed).
  const state = task?.state;
  useEffect(() => {
    setDiff(null);
    if (!taskId) return;
    let alive = true;
    delegationApi.diff(taskId).then((d) => alive && setDiff(d)).catch(() => {});
    delegationApi.opencodeUrl().then((u) => alive && setOcUrl(u)).catch(() => {});
    return () => { alive = false; };
  }, [taskId, state]);

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try { await fn(); refresh(); } catch (e) { setActionError(e instanceof Error ? e.message : String(e)); }
  }, [refresh]);

  return (
    <div className="min-h-screen p-4 text-gray-200">
      <Head><title>Workbench</title></Head>
      <div className="flex items-center gap-3 mb-3">
        <button className="glass-btn text-xs" onClick={() => router.push('/mission-control')}>Back</button>
        <h1 className="font-bold tracking-widest text-base flex-1">WORKBENCH</h1>
        <BulkControls paused={paused}
          onPause={() => act(async () => { await delegationApi.pauseAll(); setPaused(true); })}
          onResume={() => act(async () => { await delegationApi.resumeAll(); setPaused(false); })}
          onAbortAll={() => act(() => delegationApi.abortAll())} />
      </div>
      {(error || actionError) && <div className="text-xs text-red-400 mb-2">{actionError ?? error}</div>}
      <div className="grid gap-3" style={{ gridTemplateColumns: '280px 1fr' }}>
        <TaskList items={items} selectedId={selectedId} filter={filter} onFilter={setFilter} onSelect={setSelectedId} />
        <div className="flex flex-col gap-3">
          {!task ? <div className="glass-panel p-4 text-xs text-gray-500">Select a task.</div> : (
            <>
              <div className="glass-panel p-3">
                <div className="text-[10px] font-mono uppercase text-gray-400">{task.state}</div>
                <div className="text-sm">{task.brief}</div>
                {running && <button className="glass-btn text-xs mt-2" onClick={() => act(() => delegationApi.abort(task.task_id))}>Abort</button>}
              </div>
              <DecisionBar decisions={decisions}
                onAnswer={(id, allow) => act(async () => { await delegationApi.answerDecision(id, allow); setDecisions((d) => d.filter((x) => x.id !== id)); })} />
              <StepLog steps={task.steps} blocker={task.blocker} />
              <DiffView diff={diff} opencodeUrl={ocUrl} />
              <GuidanceBox running={running} onSend={(t) => act(() => delegationApi.guidance(task.task_id, t))} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
