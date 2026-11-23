/** Pure agenda and owner-control logic (B1-07), kept out of the components so it is testable. */
import type { AgendaItem, AutonomyState } from '@/services/auraApiService';

export const OPEN_STATES = ['pending', 'delivered'];
export const AGENDA_KINDS = ['reminder', 'observation'];

export const isOpen = (i: AgendaItem) => OPEN_STATES.includes(i.state);
export const pendingCount = (items: AgendaItem[]) => items.filter(isOpen).length;

/** Merge an `agenda_update` payload: open items are upserted, resolved ones leave the list. */
export function applyAgendaUpdate(items: AgendaItem[], update: Partial<AgendaItem> | null | undefined): AgendaItem[] {
  if (!update || typeof update.id !== 'string') return items;
  const rest = items.filter((i) => i.id !== update.id);
  if (update.state && !OPEN_STATES.includes(update.state)) return rest;
  if (!update.state) return items;
  const prev = items.find((i) => i.id === update.id);
  return [...rest, { ...(prev ?? {}), ...update } as AgendaItem].sort((a, b) => b.priority - a.priority);
}

export interface AgendaCalls {
  ack: (id: string) => Promise<unknown>;
  dismiss: (id: string) => Promise<unknown>;
}

/** Ack or dismiss through the API; the item is removed locally once the server accepts. */
export async function resolveAgendaItem(
  action: 'ack' | 'dismiss', id: string, items: AgendaItem[], api: AgendaCalls,
): Promise<AgendaItem[]> {
  await (action === 'ack' ? api.ack(id) : api.dismiss(id));
  return items.filter((i) => i.id !== id);
}

/** Kill asks for confirmation (injectable for tests). Returns true when the kill was sent. */
export function confirmKill(
  onKill: () => void,
  confirmFn: (m: string) => boolean = (m) => window.confirm(m),
): boolean {
  if (!confirmFn('Kill switch: stop everything Aura is doing on her own and block new autonomous actions until you resume?')) return false;
  onKill();
  return true;
}

export const mutedKinds = (s: AutonomyState | null) => new Set(s?.muted_kinds ?? []);
