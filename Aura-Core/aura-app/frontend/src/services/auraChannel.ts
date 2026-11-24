/**
 * Owner event channel client (B1-07). Contract: /ws/aura (api/websocket.py, autonomy/channel.py).
 * Envelope {v, seq, type, at, payload}. The client sends hello {last_seq} on every (re)connect and
 * presence {typing, active_view} at most once per 5 s. A replay after hello can overlap live
 * events, so events are deduped by seq. The pure helpers here carry the logic and are tested.
 */
import { API_BASE_URL } from '@/config';

export interface AuraEnvelope<P = any> { v: number; seq: number; type: string; at: string; payload: P }

export const PRESENCE_MIN_MS = 5000;
export const POLL_FAST_MS = 5000;
export const POLL_SLOW_MS = 30000;
export const WS_POLICY_CLOSE = 1008;

export function auraWsUrl(base: string = API_BASE_URL): string {
  return `${base.replace(/^http/, 'ws').replace(/\/$/, '')}/ws/aura`;
}

export function helloMessage(lastSeq: number) {
  return { type: 'hello', last_seq: lastSeq };
}

/** Dedupe by seq. Pings and anything not above the last seen seq are never delivered. */
export function acceptEvent(lastSeq: number, ev: Partial<AuraEnvelope> | null | undefined): { accept: boolean; lastSeq: number } {
  if (!ev || typeof ev.seq !== 'number' || ev.type === 'ping' || ev.seq <= lastSeq) return { accept: false, lastSeq };
  return { accept: true, lastSeq: ev.seq };
}

/** Filter a batch (replay or poll) down to unseen events, oldest first. */
export function acceptBatch(lastSeq: number, events: AuraEnvelope[]): { fresh: AuraEnvelope[]; lastSeq: number } {
  const fresh: AuraEnvelope[] = [];
  let last = lastSeq;
  for (const ev of [...events].sort((a, b) => a.seq - b.seq)) {
    const r = acceptEvent(last, ev);
    if (r.accept) { fresh.push(ev); last = r.lastSeq; }
  }
  return { fresh, lastSeq: last };
}

export interface PresenceState { typing: boolean; active_view: string | null; watching?: string | null }

/** At most one presence message per `minMs`; an unchanged state is not resent. */
export function createPresenceThrottle(
  send: (m: { type: 'presence' } & PresenceState) => void,
  now: () => number = Date.now,
  minMs = PRESENCE_MIN_MS,
) {
  let lastAt = -Infinity;
  let lastSent: PresenceState | null = null;
  return (state: PresenceState): boolean => {
    if (lastSent && lastSent.typing === state.typing && lastSent.active_view === state.active_view
        && (lastSent.watching ?? null) === (state.watching ?? null)) return false;
    const t = now();
    if (t - lastAt < minMs) return false;
    lastAt = t;
    lastSent = { ...state };
    send({ type: 'presence', ...state });
    return true;
  };
}

/** Delay before the next try when the socket is closed: slow when the flag is off (1008). */
export function pollDelay(closeCode: number | null): number {
  return closeCode === WS_POLICY_CLOSE ? POLL_SLOW_MS : POLL_FAST_MS;
}

export async function fetchAuraEvents(sinceSeq: number): Promise<{ events: AuraEnvelope[]; last_seq: number }> {
  const res = await fetch(`${API_BASE_URL}/aura/events?since_seq=${sinceSeq}`);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

export interface AuraChannelClient {
  start(): void; stop(): void; sendPresence(s: PresenceState): boolean; lastSeq(): number; connected(): boolean;
}

export function createAuraChannelClient(opts: {
  onEvent: (ev: AuraEnvelope) => void;
  onConnection?: (connected: boolean) => void;
  url?: string;
  makeSocket?: (url: string) => WebSocket;
  fetchEvents?: typeof fetchAuraEvents;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (t: unknown) => void;
  now?: () => number;
}): AuraChannelClient {
  const makeSocket = opts.makeSocket ?? ((u) => new WebSocket(u));
  const fetchEvents = opts.fetchEvents ?? fetchAuraEvents;
  const setTimer = opts.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = opts.clearTimer ?? ((t) => clearTimeout(t as ReturnType<typeof setTimeout>));
  let ws: WebSocket | null = null;
  let timer: unknown = null;
  let stopped = true;
  let open = false;
  let seq = 0;
  let givenUp = false;
  const presence = createPresenceThrottle((m) => { if (ws && open) ws.send(JSON.stringify(m)); }, opts.now);

  const deliver = (events: AuraEnvelope[]) => {
    const r = acceptBatch(seq, events);
    seq = r.lastSeq;
    r.fresh.forEach(opts.onEvent);
  };

  // The socket is closed: poll /aura/events once, then retry the socket after the delay.
  // With the flag off (1008) the buffer stays empty; after one empty poll go to a very slow retry.
  const fallback = async (closeCode: number | null) => {
    if (stopped || open) return;
    let empty = false;
    try {
      const out = await fetchEvents(seq);
      deliver(out.events);
      empty = out.events.length === 0 && out.last_seq === 0;
    } catch { empty = false; }
    if (stopped || open) return;
    if (closeCode === WS_POLICY_CLOSE && empty) givenUp = true;
    const delay = givenUp ? POLL_SLOW_MS * 4 : pollDelay(closeCode);
    if (timer) clearTimer(timer);
    timer = setTimer(connect, delay);
  };

  const connect = () => {
    if (stopped) return;
    let sock: WebSocket;
    try { sock = makeSocket(opts.url ?? auraWsUrl()); } catch { void fallback(null); return; }
    ws = sock;
    sock.onopen = () => {
      open = true;
      opts.onConnection?.(true);
      sock.send(JSON.stringify(helloMessage(seq)));
    };
    sock.onmessage = (m: MessageEvent) => {
      try { deliver([JSON.parse(String(m.data))]); } catch { /* ignore malformed */ }
    };
    sock.onclose = (e: CloseEvent) => {
      if (ws !== sock) return;
      const was = open;
      open = false;
      if (was) opts.onConnection?.(false);
      if (!stopped) void fallback(e?.code ?? null);
    };
    sock.onerror = () => { /* onclose follows */ };
  };

  return {
    start() { if (!stopped) return; stopped = false; givenUp = false; connect(); },
    stop() {
      stopped = true;
      if (timer) clearTimer(timer);
      timer = null;
      const s = ws;
      ws = null; open = false;
      if (s) { try { s.close(); } catch { /* ignore */ } }
    },
    sendPresence: presence,
    lastSeq: () => seq,
    connected: () => open,
  };
}
