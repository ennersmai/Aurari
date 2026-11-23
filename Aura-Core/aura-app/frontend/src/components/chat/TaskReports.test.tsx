import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi } from 'vitest';
import {
  groupTaskReports, ProgressGroupView, EscalationControlsView, TaskGraphTag, answerEscalation,
  type ReportableMessage,
} from './TaskReports';
import { createTaskReportPoller, TASK_REPORT_POLL_MS } from '@/services/taskReportService';

const mk = (id: string, kind: string | null, content = id, extra: Record<string, unknown> = {}): ReportableMessage => ({
  id, content, role: kind || id === 'u' ? 'assistant' : 'user', timestamp: `2026-11-23T00:00:0${id.length}`,
  conversationId: 'conversation:1',
  meta: kind ? { task_graph: 'task_graph:g1', kind, ...extra } : null,
});

/** Find elements in a React element tree (no DOM in this vitest env). */
function findAll(node: any, pred: (el: any) => boolean, out: any[] = []): any[] {
  if (!node || typeof node !== 'object') return out;
  if (Array.isArray(node)) { node.forEach((n) => findAll(n, pred, out)); return out; }
  if (pred(node)) out.push(node);
  findAll(node.props?.children, pred, out);
  return out;
}
const buttonByText = (tree: any, text: string) =>
  findAll(tree, (e) => e.type === 'button' && ([] as any[]).concat(e.props.children).join('') === text)[0];

describe('P2-11 progress grouping', () => {
  it('groups consecutive progress messages of one graph and leaves the rest alone', () => {
    const items = groupTaskReports([
      mk('plan', 'plan'), mk('p1', 'progress'), mk('p2', 'progress'), mk('final', 'final'),
      mk('p3', 'progress'),
    ]);
    expect(items.map((i) => i.type)).toEqual(['message', 'progress', 'message', 'progress']);
    expect((items[1] as any).messages.map((m: any) => m.id)).toEqual(['p1', 'p2']);
  });

  it('is collapsed to one muted line and opens to every line', () => {
    const msgs = [mk('a', 'progress', "research 'prices' done"), mk('b', 'progress', "code 'api' failed: boom")];
    const closed = renderToStaticMarkup(<ProgressGroupView messages={msgs} open={false} onToggle={() => {}} />);
    expect(closed).toContain('data-open="false"');
    expect(closed).toContain('failed: boom');
    expect(closed).not.toContain('progress-line');
    const open = renderToStaticMarkup(<ProgressGroupView messages={msgs} open onToggle={() => {}} />);
    expect(open).toContain('data-open="true"');
    expect(open.match(/data-testid="progress-line"/g)).toHaveLength(2);
    expect(open).toContain("research &#x27;prices&#x27; done");
  });

  it('the toggle button calls onToggle', () => {
    const onToggle = vi.fn();
    const tree = ProgressGroupView({ messages: [mk('a', 'progress')], open: false, onToggle });
    findAll(tree, (e) => e.type === 'button')[0].props.onClick();
    expect(onToggle).toHaveBeenCalledOnce();
  });
});

describe('P2-11 tag', () => {
  it('shows the task graph tag on plan, final and escalation, not on progress or plain messages', () => {
    for (const kind of ['plan', 'final']) {
      const html = renderToStaticMarkup(<TaskGraphTag meta={{ task_graph: 'g', kind }} />);
      expect(html).toContain('task graph');
      expect(html).toContain(`data-kind="${kind}"`);
    }
    expect(renderToStaticMarkup(<TaskGraphTag meta={{ task_graph: 'g', kind: 'escalation' }} />)).toContain('needs you');
    expect(renderToStaticMarkup(<TaskGraphTag meta={{ task_graph: 'g', kind: 'progress' }} />)).toBe('');
    expect(renderToStaticMarkup(<TaskGraphTag meta={null} />)).toBe('');
  });
});

describe('P2-11 escalation', () => {
  it('Approve and Reject call the API with the decision id', async () => {
    const onAnswer = vi.fn();
    const tree = EscalationControlsView({ decisionId: 'decision:abc', state: 'pending', onAnswer });
    buttonByText(tree, 'Approve').props.onClick();
    buttonByText(tree, 'Reject').props.onClick();
    expect(onAnswer).toHaveBeenNthCalledWith(1, 'decision:abc', true);
    expect(onAnswer).toHaveBeenNthCalledWith(2, 'decision:abc', false);

    const api = { answerDecision: vi.fn().mockResolvedValue({}) };
    expect(await answerEscalation('decision:abc', true, api)).toBe('approved');
    expect(await answerEscalation('decision:abc', false, api)).toBe('rejected');
    expect(api.answerDecision).toHaveBeenNthCalledWith(1, 'decision:abc', true);
    expect(api.answerDecision).toHaveBeenNthCalledWith(2, 'decision:abc', false);
  });

  it('POSTs /decisions/{id} with {allow} through the delegation client', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
    await answerEscalation('decision:abc', true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/decisions/decision%3Aabc');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ allow: true });
    vi.unstubAllGlobals();
  });

  it('shows the outcome instead of the buttons once answered, and disables while sending', () => {
    expect(renderToStaticMarkup(<EscalationControlsView decisionId="d" state="approved" onAnswer={() => {}} />))
      .toContain('You approved this.');
    const sending = renderToStaticMarkup(<EscalationControlsView decisionId="d" state="sending" onAnswer={() => {}} />);
    expect(sending).toContain('disabled');
  });
});

describe('P2-11 polling', () => {
  it('polls every 5 s while running, passes since, and stops when nothing runs', async () => {
    const timers: Array<{ fn: () => void; ms: number }> = [];
    const responses = [
      { messages: [mk('a', 'plan')], running: true },
      { messages: [mk('bb', 'progress')], running: true },
      { messages: [mk('ccc', 'final')], running: false },
    ];
    const fetchReports = vi.fn(async () => responses.shift()!);
    const seen: string[] = [];
    const poller = createTaskReportPoller({
      conversationId: 'conversation:1', fetchReports, onMessages: (m) => seen.push(...m.map((x) => x.id)),
      setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimer: () => {},
    });
    poller.start();
    await vi.waitFor(() => expect(timers).toHaveLength(1));
    expect(timers[0].ms).toBe(TASK_REPORT_POLL_MS);
    poller.start(); // does not stack
    expect(fetchReports).toHaveBeenCalledTimes(1);
    timers[0].fn();
    await vi.waitFor(() => expect(timers).toHaveLength(2));
    timers[1].fn();
    await vi.waitFor(() => expect(fetchReports).toHaveBeenCalledTimes(3));
    await new Promise((r) => setTimeout(r, 0));
    expect(timers).toHaveLength(2); // nothing scheduled after running=false
    expect(seen).toEqual(['a', 'bb', 'ccc']);
    expect((fetchReports.mock.calls as any[]).map((c) => c[1])).toEqual([undefined, mk('a', 'plan').timestamp, mk('bb', 'progress').timestamp]);
  });
});
