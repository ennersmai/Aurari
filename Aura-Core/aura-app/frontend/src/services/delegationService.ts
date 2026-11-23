/**
 * Delegation (Workbench) API client (G4-03). Contract: api/routes/delegations.py (G4-01)
 * and api/routes/decisions.py. G4-02 fields are optional so this works before and after it.
 */
import { API_BASE_URL } from '@/config';

export type DelegationStepType = 'guidance' | 'heartbeat' | string;

export interface DelegationStep {
  step_number?: number;
  step_type?: DelegationStepType;
  type?: DelegationStepType;
  description?: string;
  summary?: string;
  result?: string | null;
  emotion?: Record<string, number> | null;
  [key: string]: unknown;
}

export interface DelegationBlocker {
  kind?: string;
  reason?: string;
  suggestion?: string | null;
  [key: string]: unknown;
}

export interface Delegation {
  task_id: string;
  state: string;
  brief: string;
  session_id?: string;
  workspace?: string | null;
  budget?: Record<string, unknown> | null;
  steps: DelegationStep[];
  step_count: number;
  blocker?: DelegationBlocker | string | null;
  pending_decision_ids: string[];
  created_at: string;
  completed_at?: string | null;
}

export interface DelegationDiff {
  files_changed: string[];
  additions: number;
  deletions: number;
  summary: string;
}

export interface PendingDecision {
  id: string;
  task_id?: string;
  [key: string]: unknown;
}

export const CLOSED_STATES = ['completed', 'failed', 'cancelled', 'canceled', 'aborted'];
export const isRunningState = (s: string) => s === 'running';
export const isClosedState = (s: string) => CLOSED_STATES.includes((s || '').toLowerCase());

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json())?.detail ?? ''; } catch { /* ignore */ }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;
const post = (path: string, body?: unknown) =>
  req<any>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const delegationApi = {
  list: () => req<{ paused: boolean; delegations: Delegation[] }>('/delegations'),
  get: async (id: string) => (await req<{ delegation: Delegation }>(`/delegations/${enc(id)}`)).delegation,
  diff: (id: string) => req<DelegationDiff>(`/delegations/${enc(id)}/diff`),
  opencodeUrl: async () => (await req<{ url: string | null }>('/delegations/opencode-url')).url,
  abort: (id: string) => post(`/delegations/${enc(id)}/abort`),
  guidance: (id: string, text: string) => post(`/delegations/${enc(id)}/guidance`, { text }),
  abortAll: () => post('/delegations/abort-all'),
  pauseAll: () => post('/delegations/pause-all'),
  resumeAll: () => post('/delegations/resume-all'),
  pendingDecisions: async () => (await req<{ decisions: PendingDecision[] }>('/decisions')).decisions,
  answerDecision: (id: string, allow: boolean) => post(`/decisions/${enc(id)}`, { allow }),
};
export type DelegationApi = typeof delegationApi;
