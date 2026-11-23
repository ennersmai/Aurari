/**
 * Task graph reports (P2-11). The backend has no push channel to the chat, so the page
 * polls GET /chat/task-reports while a graph of the conversation is running.
 */
import { API_BASE_URL } from '@/config';
import type { ReportableMessage } from '@/components/chat/TaskReports';

export const TASK_REPORT_POLL_MS = 5000;

export interface TaskReportsResponse { messages: ReportableMessage[]; running: boolean }

export async function fetchTaskReports(conversationId: string, since?: string): Promise<TaskReportsResponse> {
  const qs = new URLSearchParams({ conversation_id: conversationId });
  if (since) qs.set('since', since);
  const res = await fetch(`${API_BASE_URL}/chat/task-reports?${qs.toString()}`);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

/**
 * Polls while a graph runs: one poll at once, then every `intervalMs` until a response says
 * nothing is running. `start()` is safe to call again (it does not stack timers).
 */
export function createTaskReportPoller(opts: {
  conversationId: string;
  fetchReports?: typeof fetchTaskReports;
  onMessages: (messages: ReportableMessage[]) => void;
  intervalMs?: number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (t: unknown) => void;
}) {
  const fetchReports = opts.fetchReports ?? fetchTaskReports;
  const setTimer = opts.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = opts.clearTimer ?? ((t) => clearTimeout(t as ReturnType<typeof setTimeout>));
  let timer: unknown = null;
  let busy = false;
  let stopped = false;
  let since: string | undefined;

  const poll = async () => {
    timer = null;
    if (stopped || busy) return;
    busy = true;
    let running = true; // a failed request is not the end of the graph: keep polling
    try {
      const out = await fetchReports(opts.conversationId, since);
      if (out.messages.length) {
        since = out.messages[out.messages.length - 1].timestamp;
        opts.onMessages(out.messages);
      }
      running = out.running;
    } catch {
      /* keep polling */
    }
    busy = false;
    if (running && !stopped) timer = setTimer(poll, opts.intervalMs ?? TASK_REPORT_POLL_MS);
  };

  return {
    start() {
      if (timer === null && !busy && !stopped) void poll();
    },
    stop() {
      stopped = true;
      if (timer !== null) clearTimer(timer);
      timer = null;
    },
  };
}
