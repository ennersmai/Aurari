import React, { useState } from 'react';
import { delegationApi } from '@/services/delegationService';

/** Meta of a task graph report message (P2-11). Contract: executor/task_reports.py. */
export interface TaskReportMeta {
  task_graph: string;
  kind: 'plan' | 'progress' | 'final' | 'escalation' | string;
  decision_id?: string;
}

export interface ReportableMessage {
  id: string;
  content: string;
  role: string;
  timestamp: string;
  conversationId: string;
  meta?: TaskReportMeta | null;
  [key: string]: unknown;
}

export type ChatItem<M extends ReportableMessage = ReportableMessage> =
  | { type: 'message'; message: M }
  | { type: 'progress'; graph: string; messages: M[] };

export const isProgress = (m: ReportableMessage) => m.meta?.kind === 'progress' && !!m.meta?.task_graph;

/** Consecutive progress messages of one graph become one group; others stay as they are. */
export function groupTaskReports<M extends ReportableMessage>(messages: M[]): ChatItem<M>[] {
  const items: ChatItem<M>[] = [];
  for (const message of messages) {
    if (isProgress(message)) {
      const last = items[items.length - 1];
      if (last && last.type === 'progress' && last.graph === message.meta!.task_graph) {
        last.messages.push(message);
        continue;
      }
      items.push({ type: 'progress', graph: message.meta!.task_graph, messages: [message] });
    } else {
      items.push({ type: 'message', message });
    }
  }
  return items;
}

/** The small tag on plan, final and escalation messages. */
export function TaskGraphTag({ meta }: { meta?: TaskReportMeta | null }) {
  if (!meta?.task_graph || meta.kind === 'progress') return null;
  return (
    <span
      className="task-graph-tag"
      data-testid="task-graph-tag"
      data-kind={meta.kind}
      style={{
        fontSize: '0.6rem', padding: '1px 6px', marginLeft: 8, borderRadius: 8,
        border: '1px solid rgba(192, 156, 88, 0.4)', color: 'rgba(192, 156, 88, 0.9)',
      }}
    >
      task graph{meta.kind === 'escalation' ? ': needs you' : ''}
    </span>
  );
}

/** Pure view: a one-line muted summary that opens to the progress lines. */
export function ProgressGroupView({ messages, open, onToggle }: {
  messages: ReportableMessage[]; open: boolean; onToggle: () => void;
}) {
  const last = messages[messages.length - 1];
  return (
    <div
      data-testid="progress-group"
      data-open={open ? 'true' : 'false'}
      style={{ margin: '0 0 12px 58px', fontSize: '0.75rem', opacity: 0.7 }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0 }}
      >
        {open ? 'Hide' : 'Show'} task progress ({messages.length}){open ? '' : `: ${last.content}`}
      </button>
      {open && (
        <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
          {messages.map((m) => <li key={m.id} data-testid="progress-line">{m.content}</li>)}
        </ul>
      )}
    </div>
  );
}

export function ProgressGroup({ messages }: { messages: ReportableMessage[] }) {
  const [open, setOpen] = useState(false);
  return <ProgressGroupView messages={messages} open={open} onToggle={() => setOpen((o) => !o)} />;
}

type EscalationState = 'pending' | 'sending' | 'approved' | 'rejected';

/** Pure view of the Approve and Reject buttons. */
export function EscalationControlsView({ decisionId, state, error, onAnswer }: {
  decisionId: string; state: EscalationState; error?: string;
  onAnswer: (decisionId: string, allow: boolean) => void;
}) {
  if (state === 'approved' || state === 'rejected') {
    return <div data-testid="escalation-done" style={{ fontSize: '0.75rem', marginTop: 6 }}>You {state} this.</div>;
  }
  const disabled = state === 'sending';
  return (
    <div data-testid="escalation-controls" style={{ display: 'flex', gap: 8, marginTop: 8 }}>
      <button type="button" disabled={disabled} onClick={() => onAnswer(decisionId, true)}>Approve</button>
      <button type="button" disabled={disabled} onClick={() => onAnswer(decisionId, false)}>Reject</button>
      {error && <span style={{ fontSize: '0.75rem' }}>{error}</span>}
    </div>
  );
}

/** Calls POST /decisions/{id} with {allow}, the same call as the Workbench's DecisionBar. */
export async function answerEscalation(
  decisionId: string,
  allow: boolean,
  api: { answerDecision: (id: string, allow: boolean) => Promise<unknown> } = delegationApi,
): Promise<'approved' | 'rejected'> {
  await api.answerDecision(decisionId, allow);
  return allow ? 'approved' : 'rejected';
}

export function EscalationControls({ decisionId }: { decisionId: string }) {
  const [state, setState] = useState<EscalationState>('pending');
  const [error, setError] = useState<string | undefined>();
  const onAnswer = async (id: string, allow: boolean) => {
    setState('sending');
    setError(undefined);
    try {
      setState(await answerEscalation(id, allow));
    } catch (e) {
      setState('pending');
      setError((e as Error).message);
    }
  };
  return <EscalationControlsView decisionId={decisionId} state={state} error={error} onAnswer={onAnswer} />;
}
