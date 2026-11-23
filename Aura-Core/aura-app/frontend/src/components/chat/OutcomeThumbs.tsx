import React, { useState, useSyncExternalStore } from 'react';
import { outcomeApi } from '@/services/auraApiService';

/** Session gate: the first 404 from /chat/outcome (flag off) hides the thumbs everywhere. */
export function createThumbsGate() {
  let hidden = false;
  const subs = new Set<() => void>();
  return {
    isHidden: () => hidden,
    hide() { if (!hidden) { hidden = true; subs.forEach((f) => f()); } },
    subscribe(f: () => void) { subs.add(f); return () => { subs.delete(f); }; },
  };
}
export const thumbsGate = createThumbsGate();

/** Send a thumb; hides the controls on a 404 (flag off). A 404 that only says this one message
 *  has no experience yet ("No experience ...") leaves the controls alone. Returns true when recorded. */
export async function sendThumb(
  messageId: string, signal: 'up' | 'down',
  send: (id: string, s: 'up' | 'down') => Promise<unknown> = outcomeApi.send,
  gate = thumbsGate,
): Promise<boolean> {
  try { await send(messageId, signal); return true; }
  catch (e: any) { if (e?.status === 404 && !String(e?.detail ?? '').startsWith('No experience')) gate.hide(); return false; }
}

export function ThumbsView({ chosen, onThumb }: { chosen: 'up' | 'down' | null; onThumb: (s: 'up' | 'down') => void }) {
  const btn = (s: 'up' | 'down', label: string, glyph: string) => (
    <button
      type="button" className="glass-btn-icon" aria-label={label} aria-pressed={chosen === s}
      disabled={chosen !== null} onClick={() => onThumb(s)}
      style={{ opacity: chosen && chosen !== s ? 0.3 : 0.7, fontSize: 12, padding: '0 6px' }}
    >{glyph}</button>
  );
  return (
    <span data-testid="outcome-thumbs" style={{ display: 'inline-flex', gap: 2, marginLeft: 6 }}>
      {btn('up', 'Good reply', '\u{1F44D}')}
      {btn('down', 'Bad reply', '\u{1F44E}')}
    </span>
  );
}

/** Thumbs for one assistant message; renders nothing once the route has answered 404. */
export function OutcomeThumbs({ messageId }: { messageId: string }) {
  const hidden = useSyncExternalStore(thumbsGate.subscribe, thumbsGate.isHidden, () => false);
  const [chosen, setChosen] = useState<'up' | 'down' | null>(null);
  if (hidden) return null;
  return (
    <ThumbsView
      chosen={chosen}
      onThumb={(s) => { setChosen(s); void sendThumb(messageId, s).then((ok) => { if (!ok) setChosen(null); }); }}
    />
  );
}
