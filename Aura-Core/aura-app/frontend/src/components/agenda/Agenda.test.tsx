import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi } from 'vitest';
import { AgendaIndicator } from './AgendaIndicator';
import { AgendaPanel } from './AgendaPanel';
import { AutonomyControls } from './AutonomyControls';
import { applyAgendaUpdate, confirmKill, pendingCount, resolveAgendaItem } from './agendaState';
import { ThumbsView, createThumbsGate, sendThumb } from '@/components/chat/OutcomeThumbs';
import {
  acceptBatch, acceptEvent, createAuraChannelClient, createPresenceThrottle, helloMessage, pollDelay,
  type AuraEnvelope,
} from '@/services/auraChannel';
import type { AgendaItem, AutonomyState } from '@/services/auraApiService';

const item = (id: string, state = 'pending', priority = 0.5): AgendaItem => ({
  id, kind: 'reminder', content: `do ${id}`, refs: [], priority, state,
});
const ev = (seq: number, type = 'agenda_update', payload: any = {}): AuraEnvelope => ({ v: 1, seq, type, at: '', payload });

function findAll(node: any, pred: (el: any) => boolean, out: any[] = []): any[] {
  if (!node || typeof node !== 'object') return out;
  if (Array.isArray(node)) { node.forEach((n) => findAll(n, pred, out)); return out; }
  if (pred(node)) out.push(node);
  findAll(node.props?.children, pred, out);
  return out;
}
const buttonByText = (tree: any, text: string) =>
  findAll(tree, (e) => e.type === 'button' && ([] as any[]).concat(e.props.children).join('') === text)[0];

describe('seq dedupe and reconnect', () => {
  it('drops seen seqs, pings and replays that overlap live events', () => {
    expect(acceptEvent(3, ev(3)).accept).toBe(false);
    expect(acceptEvent(3, ev(4)).accept).toBe(true);
    expect(acceptEvent(3, { ...ev(9), type: 'ping' }).accept).toBe(false);
    const r = acceptBatch(2, [ev(5), ev(3), ev(4), ev(3), ev(2)]);
    expect(r.fresh.map((e) => e.seq)).toEqual([3, 4, 5]);
    expect(r.lastSeq).toBe(5);
  });

  it('resends hello with the last seq after a reconnect and dedupes the replay', () => {
    const sockets: any[] = [];
    const makeSocket = () => {
      const s: any = { sent: [] as string[], send(m: string) { this.sent.push(m); }, close() {} };
      sockets.push(s);
      return s;
    };
    const got: number[] = [];
    const timers: Array<() => void> = [];
    const client = createAuraChannelClient({
      onEvent: (e) => got.push(e.seq), makeSocket: makeSocket as any,
      fetchEvents: async () => ({ events: [], last_seq: 0 }),
      setTimer: (fn) => { timers.push(fn); return timers.length; }, clearTimer: () => {},
    });
    client.start();
    sockets[0].onopen();
    expect(JSON.parse(sockets[0].sent[0])).toEqual(helloMessage(0));
    sockets[0].onmessage({ data: JSON.stringify(ev(1)) });
    sockets[0].onmessage({ data: JSON.stringify(ev(2)) });
    sockets[0].onclose({ code: 1006 });
    return Promise.resolve().then(() => Promise.resolve()).then(() => Promise.resolve()).then(() => {
      timers.pop()!(); // retry the socket
      sockets[1].onopen();
      expect(JSON.parse(sockets[1].sent[0])).toEqual({ type: 'hello', last_seq: 2 });
      sockets[1].onmessage({ data: JSON.stringify(ev(2)) }); // replay overlaps
      sockets[1].onmessage({ data: JSON.stringify(ev(3)) });
      expect(got).toEqual([1, 2, 3]);
      client.stop();
    });
  });

  it('polls slowly when the flag closes the socket with 1008', () => {
    expect(pollDelay(1008)).toBe(30000);
    expect(pollDelay(1006)).toBeLessThan(30000);
  });

  it('sends presence at most once every 5 s', () => {
    let t = 0;
    const sent: any[] = [];
    const send = createPresenceThrottle((m) => sent.push(m), () => t);
    expect(send({ typing: true, active_view: 'chat' })).toBe(true);
    t = 1000;
    expect(send({ typing: false, active_view: 'chat' })).toBe(false);
    t = 5000;
    expect(send({ typing: false, active_view: 'chat' })).toBe(true);
    t = 12000;
    expect(send({ typing: false, active_view: 'chat' })).toBe(false); // unchanged
    expect(sent).toHaveLength(2);
  });
});

describe('quiet indicator', () => {
  it('shows a badge only when items are pending', () => {
    const items = [item('a'), item('b', 'delivered'), item('c', 'acknowledged')];
    expect(pendingCount(items)).toBe(2);
    expect(renderToStaticMarkup(<AgendaIndicator count={2} />)).toContain('agenda-badge');
    expect(renderToStaticMarkup(<AgendaIndicator count={0} />)).not.toContain('agenda-badge');
  });
  it('agenda_update upserts open items and drops resolved ones', () => {
    let items = applyAgendaUpdate([], item('a'));
    expect(items).toHaveLength(1);
    items = applyAgendaUpdate(items, { id: 'a', state: 'acknowledged' });
    expect(items).toHaveLength(0);
  });
});

describe('agenda ack and dismiss', () => {
  it('buttons call back and the API is called with the item id', async () => {
    const onAck = vi.fn(); const onDismiss = vi.fn();
    const tree = AgendaPanel({ items: [item('agenda:1')], onAck, onDismiss });
    buttonByText(tree, 'Acknowledge').props.onClick();
    buttonByText(tree, 'Dismiss').props.onClick();
    expect(onAck).toHaveBeenCalledWith('agenda:1');
    expect(onDismiss).toHaveBeenCalledWith('agenda:1');

    const api = { ack: vi.fn().mockResolvedValue({}), dismiss: vi.fn().mockResolvedValue({}) };
    const items = [item('agenda:1'), item('agenda:2')];
    expect((await resolveAgendaItem('ack', 'agenda:1', items, api)).map((i) => i.id)).toEqual(['agenda:2']);
    expect((await resolveAgendaItem('dismiss', 'agenda:2', items, api)).map((i) => i.id)).toEqual(['agenda:1']);
    expect(api.ack).toHaveBeenCalledWith('agenda:1');
    expect(api.dismiss).toHaveBeenCalledWith('agenda:2');
  });
  it('keeps the item when the API fails', async () => {
    const api = { ack: vi.fn().mockRejectedValue(new Error('409')), dismiss: vi.fn() };
    await expect(resolveAgendaItem('ack', 'a', [item('a')], api)).rejects.toThrow();
  });
});

describe('owner controls', () => {
  const state = (over: Partial<AutonomyState> = {}): AutonomyState =>
    ({ level: 'important', muted_kinds: [], killed: false, killed_at: null, ...over });
  const noop = () => {};
  const props = { onLevel: noop, onMute: noop, onUnmute: noop, onKill: noop, onResume: noop };

  it('kill needs a confirm', () => {
    const onKill = vi.fn();
    expect(confirmKill(onKill, () => false)).toBe(false);
    expect(onKill).not.toHaveBeenCalled();
    expect(confirmKill(onKill, () => true)).toBe(true);
    expect(onKill).toHaveBeenCalledTimes(1);
    const tree = AutonomyControls({ state: state(), ...props, onKill, confirmFn: () => false });
    const kill = findAll(tree, (e) => e?.props?.['data-testid'] === 'kill-button')[0];
    kill.props.onClick();
    expect(onKill).toHaveBeenCalledTimes(1);
  });
  it('shows the killed state clearly and offers resume instead of kill', () => {
    const html = renderToStaticMarkup(<AutonomyControls state={state({ killed: true, killed_at: '2026-11-24T01:00:00' })} {...props} />);
    expect(html).toContain('KILLED');
    expect(html).toContain('Resume autonomy');
    expect(html).not.toContain('kill-button');
    expect(renderToStaticMarkup(<AgendaIndicator count={0} killed />)).toContain('Stopped');
  });
  it('shows level and mute state', () => {
    const html = renderToStaticMarkup(<AutonomyControls state={state({ muted_kinds: ['observation'] })} {...props} />);
    expect(html).toContain('silent');
    expect(html).toContain('Mute reminder');
    expect(html).toMatch(/checked=""[^>]*\/>Mute observation/);
  });
});

describe('thumbs', () => {
  it('call the API with message_id and signal', async () => {
    const send = vi.fn().mockResolvedValue({});
    expect(await sendThumb('message:1', 'up', send, createThumbsGate())).toBe(true);
    expect(send).toHaveBeenCalledWith('message:1', 'up');
    expect(renderToStaticMarkup(<ThumbsView chosen={null} onThumb={() => {}} />)).toContain('outcome-thumbs');
  });
  it('hide after the first 404 (flag off) but not on a per-message miss', async () => {
    const gate = createThumbsGate();
    const miss = Object.assign(new Error('404'), { status: 404, detail: 'No experience for that message' });
    expect(await sendThumb('m', 'down', vi.fn().mockRejectedValue(miss), gate)).toBe(false);
    expect(gate.isHidden()).toBe(false);
    const off = Object.assign(new Error('404'), { status: 404, detail: 'Not found' });
    expect(await sendThumb('m', 'down', vi.fn().mockRejectedValue(off), gate)).toBe(false);
    expect(gate.isHidden()).toBe(true);
  });
});
