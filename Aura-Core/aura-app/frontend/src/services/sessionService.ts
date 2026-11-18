import { API_BASE_URL } from "@/config";

// V1PRD §4 — Session abstraction.
// Aura's emotion stays SHARED across sessions; sessions scope memory + identity overlays + agents.

export type SessionMode = "main" | "scoped" | "ephemeral";
export type SessionStatus = "queued" | "active" | "paused" | "ended";

export interface IdentityOverlay {
  core_values?: Record<string, number> | null;
  relevant_preferences?: Record<string, unknown> | null;
  capabilities?: string[] | null;
  narrative_suffix?: string | null;
}

export interface Session {
  session_id: string;
  name: string;
  mode: SessionMode;
  owner: string;
  parent_session_id: string | null;
  status: SessionStatus;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  memory_namespace: string;
  emotion_isolated: boolean; // hard rule: defaults false; treat True as a deliberate flag
  identity_overlay: IdentityOverlay | null;
  model_overrides: Record<string, string>;
  tool_allowlist: string[] | null;
  tool_denylist: string[];
  max_concurrent_agents: number;
  active_agent_ids?: string[];
  completed_task_ids?: string[];
}

export interface CreateSessionPayload {
  name: string;
  mode?: SessionMode;
  owner?: string;
  parent_session_id?: string | null;
  identity_overlay?: IdentityOverlay | null;
  model_overrides?: Record<string, string>;
  tool_allowlist?: string[] | null;
  tool_denylist?: string[];
  max_concurrent_agents?: number;
  emotion_isolated?: boolean;
}

export interface UpdateSessionPayload {
  name?: string;
  model_overrides?: Record<string, string>;
  tool_allowlist?: string[] | null;
  tool_denylist?: string[];
  max_concurrent_agents?: number;
  identity_overlay?: IdentityOverlay | null;
}

interface SessionResponse {
  success: boolean;
  session?: Session;
  sessions?: Session[];
  message?: string;
}

interface SessionStateResponse {
  session: Session;
  attached_agent_ids: string[];
  main: boolean;
}

async function jsonOrThrow(res: Response): Promise<unknown> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = (body as { detail?: string })?.detail || JSON.stringify(body);
    } catch {
      // ignore parse errors; use statusText
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

const sessionService = {
  async list(opts: { status?: SessionStatus; owner?: string } = {}): Promise<Session[]> {
    const qs = new URLSearchParams();
    if (opts.status) qs.set("status", opts.status);
    if (opts.owner) qs.set("owner", opts.owner);
    const suffix = qs.toString() ? `?${qs}` : "";
    const res = await fetch(`${API_BASE_URL}/sessions${suffix}`);
    const data = (await jsonOrThrow(res)) as SessionResponse;
    return data.sessions ?? [];
  },

  async get(sessionId: string): Promise<Session | null> {
    const res = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}`);
    if (res.status === 404) return null;
    const data = (await jsonOrThrow(res)) as SessionResponse;
    return data.session ?? null;
  },

  async create(payload: CreateSessionPayload): Promise<Session> {
    const res = await fetch(`${API_BASE_URL}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = (await jsonOrThrow(res)) as SessionResponse;
    if (!data.session) throw new Error("create_session: missing session in response");
    return data.session;
  },

  async update(sessionId: string, patch: UpdateSessionPayload): Promise<Session> {
    const res = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    const data = (await jsonOrThrow(res)) as SessionResponse;
    if (!data.session) throw new Error("update_session: missing session in response");
    return data.session;
  },

  async start(sessionId: string): Promise<Session> {
    const res = await fetch(
      `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/start`,
      { method: "POST" },
    );
    const data = (await jsonOrThrow(res)) as SessionResponse;
    return data.session as Session;
  },

  async pause(sessionId: string): Promise<Session> {
    const res = await fetch(
      `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/pause`,
      { method: "POST" },
    );
    const data = (await jsonOrThrow(res)) as SessionResponse;
    return data.session as Session;
  },

  async resume(sessionId: string): Promise<Session> {
    const res = await fetch(
      `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/resume`,
      { method: "POST" },
    );
    const data = (await jsonOrThrow(res)) as SessionResponse;
    return data.session as Session;
  },

  async end(
    sessionId: string,
    opts: { merge_emotion?: boolean; archive_memory?: boolean } = {},
  ): Promise<Session> {
    const res = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/end`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merge_emotion: opts.merge_emotion ?? false,
        archive_memory: opts.archive_memory ?? true,
      }),
    });
    const data = (await jsonOrThrow(res)) as SessionResponse;
    return data.session as Session;
  },

  async state(sessionId: string): Promise<SessionStateResponse> {
    const res = await fetch(
      `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/state`,
    );
    return (await jsonOrThrow(res)) as SessionStateResponse;
  },

  isMain(sessionId: string | null | undefined): boolean {
    return !sessionId || sessionId === "main" || sessionId === "session:main";
  },
};

export default sessionService;
