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

/** P2-33 autonomy slider levels (Phase 2 plan, Part 11). */
export const AUTONOMY_LEVELS: { level: 0 | 1 | 2 | 3; name: string; may: string }[] = [
  { level: 0, name: 'Reactive', may: 'only replies' },
  { level: 1, name: 'Attentive', may: 'follows up on her agenda and promised work' },
  { level: 2, name: 'Proactive', may: 'also starts conversations, shares ideas, proposes goals' },
  { level: 3, name: 'Autonomous', may: 'also pursues approved goals, task graphs on Titan' },
];

const BUDGET_LABELS: Record<string, string> = { messages: 'messages', sage_calls: 'Sage calls', task_graphs: 'task graphs' };

/** "2/6 messages, 0/5 Sage calls" for the budgets that are not zero at this level. */
export function budgetSummary(state: AutonomyState | null): string {
  const res = state?.budget?.resources;
  if (!res) return '';
  return Object.entries(res)
    .filter(([, b]) => b.limit > 0)
    .map(([k, b]) => `${b.used}/${b.limit} ${BUDGET_LABELS[k] ?? k}`)
    .join(', ');
}

/** Shown when the tier caps the slider: the level Aura really acts at. */
export function cappedNote(state: AutonomyState | null): string | null {
  if (!state || state.effective_level === undefined || state.effective_level >= state.level) return null;
  const name = AUTONOMY_LEVELS[state.effective_level]?.name ?? String(state.effective_level);
  return `This tier caps it at ${state.effective_level} (${name}).`;
}
