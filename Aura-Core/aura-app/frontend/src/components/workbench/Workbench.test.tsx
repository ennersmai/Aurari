import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { TaskList } from './TaskList';
import { StepLog } from './StepLog';
import { DecisionBar } from './DecisionBar';
import { GuidanceBox } from './GuidanceBox';
import { DiffView } from './DiffView';
import { handleAbortAll } from './BulkControls';
import { createDelegationPoller } from '@/hooks/useDelegations';
import { delegationApi, type Delegation } from '@/services/delegationService';

const mk = (id: string, state: string, extra: Partial<Delegation> = {}): Delegation => ({
  task_id: id, state, brief: `brief ${id}`, steps: [], step_count: 0, pending_decision_ids: [],
  created_at: '2026-11-23T00:00:00', ...extra,
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

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('G4-03 task list', () => {
  it('renders tasks with state badges and filters', () => {
    const items = [mk('a', 'running'), mk('b', 'completed'), mk('c', 'failed')];
    const html = renderToStaticMarkup(<TaskList items={items} selectedId="a" filter="all" onFilter={() => {}} onSelect={() => {}} />);
    expect(html).toContain('brief a');
    expect(html).toContain('running');
    expect(html).toContain('completed');
    const closed = renderToStaticMarkup(<TaskList items={items} selectedId={null} filter="closed" onFilter={() => {}} onSelect={() => {}} />);
    expect(closed).not.toContain('brief a');
    expect(closed).toContain('brief b');
  });
});

describe('G4-03 step log', () => {
  it('shows guidance, heartbeat and blocker distinctly with the emotion tag', () => {
    const steps = [
      { step_number: 1, step_type: 'guidance', description: 'use pytest' },
      { step_number: 2, step_type: 'status', description: 'still working' },
      { step_number: 3, step_type: 'tool', description: 'edit file', emotion: { focus: 0.9, calm: 0.5, joy: 0.1, extra: 0.01 } },
    ];
    const html = renderToStaticMarkup(
      <StepLog steps={steps} blocker={{ kind: 'needs_input', reason: 'which db?', suggestion: 'use sqlite' }} />,
    );
    expect(html).toContain('data-kind="guidance"');
    expect(html).toContain('data-kind="heartbeat"');
    expect(html).toContain('data-kind="blocker"');
    expect(html).toContain('emotion-tag');
    expect(html).toContain('focus, calm, joy');
    expect(html).not.toContain('extra');
    expect(html).toContain('Suggestion: use sqlite');
  });
  it('works without G4-02 fields', () => {
    const html = renderToStaticMarkup(<StepLog steps={[{ step_number: 1, description: 'x' }]} blocker="stuck" />);
    expect(html).toContain('stuck');
    expect(html).not.toContain('emotion-tag');
  });
});

describe('G4-03 decisions', () => {
  it('approve and deny call the handler, which posts to the decisions API', async () => {
    const calls: any[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: any) => { calls.push([url, init]); return { ok: true, json: async () => ({}) }; }));
    const onAnswer = vi.fn((id: string, allow: boolean) => delegationApi.answerDecision(id, allow));
    const tree = DecisionBar({ decisions: [{ id: 'decision:1' }], onAnswer });
    buttonByText(tree, 'Approve').props.onClick();
    buttonByText(tree, 'Deny').props.onClick();
    expect(onAnswer).toHaveBeenNthCalledWith(1, 'decision:1', true);
    expect(onAnswer).toHaveBeenNthCalledWith(2, 'decision:1', false);
    await Promise.resolve();
    expect(calls[0][0]).toContain('/decisions/decision%3A1');
    expect(calls[0][1].method).toBe('POST');
    expect(JSON.parse(calls[0][1].body)).toEqual({ allow: true });
    expect(JSON.parse(calls[1][1].body)).toEqual({ allow: false });
  });
});

describe('G4-03 bulk controls', () => {
  it('abort all asks for confirmation', () => {
    const abort = vi.fn();
    handleAbortAll(abort, () => false);
    expect(abort).not.toHaveBeenCalled();
    const confirmFn = vi.fn(() => true);
    handleAbortAll(abort, confirmFn);
    expect(confirmFn).toHaveBeenCalledOnce();
    expect(abort).toHaveBeenCalledOnce();
  });
});

describe('G4-03 guidance and diff', () => {
  it('guidance box is disabled unless the task is running', () => {
    expect(renderToStaticMarkup(<GuidanceBox running={false} onSend={() => {}} />)).toMatch(/<textarea[^>]*disabled/);
    const on = renderToStaticMarkup(<GuidanceBox running onSend={() => {}} />);
    expect(on).toContain('0 / 4000');
    expect(on).toMatch(/maxLength="4000"/i);
    expect(on).not.toMatch(/<textarea[^>]*disabled/);
  });
  it('hides the OpenCode link when the url is null', () => {
    const diff = { files_changed: ['a.py'], additions: 3, deletions: 1, summary: 'did it' };
    expect(renderToStaticMarkup(<DiffView diff={diff} opencodeUrl={null} />)).not.toContain('Open in OpenCode');
    expect(renderToStaticMarkup(<DiffView diff={diff} opencodeUrl="http://x" />)).toContain('Open in OpenCode');
  });
});

describe('G4-03 polling', () => {
  it('polls the running task every 2 s and stops when it closes and on stop()', async () => {
    vi.useFakeTimers();
    let state = 'running';
    const get = vi.fn(async () => mk('a', state));
    const list = vi.fn(async () => ({ paused: false, delegations: [] as Delegation[] }));
    const p = createDelegationPoller({ api: { get, list }, onList: () => {}, onTask: () => {} });
    p.start();
    p.select('a', 'running');
    await vi.advanceTimersByTimeAsync(0);
    const initial = get.mock.calls.length;
    await vi.advanceTimersByTimeAsync(4000);
    expect(get.mock.calls.length).toBe(initial + 2);
    state = 'completed';
    await vi.advanceTimersByTimeAsync(2000); // sees closed, stops
    const afterClose = get.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(get.mock.calls.length).toBe(afterClose);
    expect(list.mock.calls.length).toBeGreaterThan(2); // list keeps polling every 5 s
    p.stop();
    const l = list.mock.calls.length;
    await vi.advanceTimersByTimeAsync(20000);
    expect(list.mock.calls.length).toBe(l);
  });
  it('does not poll a task that is already closed', async () => {
    vi.useFakeTimers();
    const get = vi.fn(async () => mk('a', 'failed'));
    const p = createDelegationPoller({ api: { get, list: async () => ({ paused: false, delegations: [] }) }, onList: () => {}, onTask: () => {} });
    p.select('a', 'failed');
    await vi.advanceTimersByTimeAsync(10000);
    expect(get).toHaveBeenCalledTimes(1);
    p.stop();
  });
});
