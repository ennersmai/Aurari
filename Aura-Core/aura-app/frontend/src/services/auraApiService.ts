/**
 * Aura Backend API Service
 * 
 * Provides typed methods for interacting with the Aura backend.
 */

import { API_BASE_URL } from '@/config';
import type { EmotionState, Memory, Goal, GoalContext } from '@/types/aura';

const API_URL = API_BASE_URL;

export interface SendMessageRequest {
  message: string;
  user_id?: string;
  conversation_history?: Array<{ role: string; content: string }>;
  stream?: boolean;
  // Optional context for persistence
  conversation_id?: string;
  session_id?: string;          // Session this chat runs under (V1PRD §4)
  // Advanced options
  context_limit?: number;      // Max conversation history messages
  // P2-42: no reasoning fields. The tier slider and the L1 route decide how much Aura thinks.
}

/** Per-turn metadata from the backend (P2-42). */
export interface TurnMeta {
  deep_reasoning: boolean;
  tier: string;
  route: string | null;
}

/** The JSON body of /chat/message and /chat/stream. Carries no reasoning controls (P2-42). */
export function buildChatRequestBody(request: SendMessageRequest, stream: boolean) {
  return {
    message: request.message,
    user_id: request.user_id || 'default',
    conversation_history: request.conversation_history || [],
    stream,
    conversation_id: request.conversation_id,
    session_id: request.session_id || 'main',
    context_limit: request.context_limit,
  };
}

export interface SendMessageResponse {
  success: boolean;
  response: string;
  emotional_state?: {
    dominant: string;
    intensity: number;
    description: string;
  };
  learning_applied?: boolean;
  deep_reasoning?: boolean;
  tier?: string;
  route?: string | null;
  debug_info?: {
    injected_memories?: string[];
    active_insights?: Array<{
      content: string;
      type: string;
      confidence: number;
    }>;
    l2_critique?: string;
    reasoning_trace?: string[];
  };
}

export interface EmotionResponse {
  success: boolean;
  data?: {
    timestamp: string;
    vector: { [key: string]: number };
    dominant: [string, number];
    secondary: [string, number];
    valence: number;
    arousal: number;
    dominance: number;
    volatility: number;
    stability: number;
    description: string;
  };
  message?: string;
}

export interface SystemStateResponse {
  state: 'ACTIVE' | 'IDLE' | 'DREAMING' | 'SLEEPING';
  state_updated_at: string;
  last_user_interaction: string;
  last_active_user_id: string;
  session_started_at: string;
  idle_after_minutes: number;
  dream_after_minutes: number;
  wake_word: string;
  auto_wake_on_query: boolean;
  dreaming_task_running: boolean;
}

export interface WakeSystemResponse {
  greeting: string;
  state: SystemStateResponse;
}

class AuraApiService {
  private baseUrl: string;

  constructor(baseUrl: string = API_URL) {
    this.baseUrl = baseUrl;
  }

  /**
   * Send message to Aura and get response
   */
  async sendMessage(request: SendMessageRequest & { onToken?: (token: string) => void }): Promise<SendMessageResponse> {
    // If streaming callback is provided, use the streaming endpoint
    if (request.onToken) {
        let turnMeta: TurnMeta | null = null;
        const streamRequest = { ...request, stream: true, onMeta: (m: TurnMeta) => { turnMeta = m; } };
        let fullResponse = "";
        
        try {
            const stream = this.streamMessage(streamRequest);
            for await (const chunk of stream) {
                fullResponse += chunk;
                request.onToken(chunk);
            }
            
            // Get final emotional state to return compliant response
            const emotionState = await this.getEmotionState().catch(() => null);
            
            return {
                success: true,
                response: fullResponse,
                emotional_state: emotionState ? {
                    dominant: emotionState.dominant,
                    intensity: 0.5, // Approximation
                    description: emotionState.current_state
                } : undefined,
                learning_applied: true,
                ...(turnMeta ? {
                  deep_reasoning: (turnMeta as TurnMeta).deep_reasoning,
                  tier: (turnMeta as TurnMeta).tier,
                  route: (turnMeta as TurnMeta).route,
                } : {}),
            };
        } catch (e) {
            console.error("Streaming failed, falling back to standard request:", e);
            // Fallback to standard request if streaming fails
        }
    }

    const response = await fetch(`${this.baseUrl}/chat/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(buildChatRequestBody(request, request.stream || false)),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `Request failed with status ${response.status}`);
    }

    return response.json();
  }

  /**
   * Stream message response (Server-Sent Events)
   */
  async *streamMessage(request: SendMessageRequest & { onMeta?: (meta: TurnMeta) => void }): AsyncGenerator<string, void, unknown> {
    const response = await fetch(`${this.baseUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      // conversation_id is CRITICAL here: the backend persists the streamed reply with it.
      body: JSON.stringify(buildChatRequestBody(request, true)),
    });

    if (!response.ok) {
      throw new Error(`Stream failed with status ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Response body is not readable');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') {
              return;
            }
            try {
                // Try parsing as JSON first (handles newlines and special chars)
                const parsed = JSON.parse(data);
                if (parsed && typeof parsed === 'object' && parsed.type === 'turn_meta') {
                  // P2-42: final turn metadata event, not text.
                  request.onMeta?.({
                    deep_reasoning: !!parsed.deep_reasoning,
                    tier: String(parsed.tier ?? ''),
                    route: parsed.route ?? null,
                  });
                  continue;
                }
                yield parsed;
            } catch {
                // Fallback to raw string (legacy)
                yield data;
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Get current emotional state
   */
  async getEmotionState(): Promise<EmotionState> {
    const response = await fetch(`${this.baseUrl}/emotion/current`);
    
    if (!response.ok) {
      throw new Error(`Failed to fetch emotion state: ${response.status}`);
    }

    const json: EmotionResponse = await response.json();
    
    if (!json.success || !json.data) {
      throw new Error(json.message || 'Failed to get emotion state');
    }

    // Transform backend response to frontend EmotionState
    const data = json.data;
    const vector = data.vector || {};
    
    return {
      // Core 8 emotions (Plutchik) - for backward compatibility
      joy: vector.joy || 0,
      trust: vector.trust || 0,
      fear: vector.fear || 0,
      surprise: vector.surprise || 0,
      sadness: vector.sadness || 0,
      disgust: vector.disgust || 0,
      anger: vector.anger || 0,
      // Note: anticipation is calculated below from interest + curiosity
      
      // All 27 emotions from the vector
      love: vector.love || 0,
      interest: vector.interest || 0,
      
      // Aesthetic emotions
      awe: vector.awe || 0,
      beauty: vector.beauty || 0,
      wonder: vector.wonder || 0,
      serenity: vector.serenity || 0,
      melancholy: vector.melancholy || 0,
      nostalgia: vector.nostalgia || 0,
      
      // Social emotions
      empathy: vector.empathy || 0,
      gratitude: vector.gratitude || 0,
      pride: vector.pride || 0,
      shame: vector.shame || 0,
      envy: vector.envy || 0,
      compassion: vector.compassion || 0,
      
      // Cognitive emotions
      curiosity: vector.curiosity || 0,
      confusion: vector.confusion || 0,
      certainty: vector.certainty || 0,
      doubt: vector.doubt || 0,
      fascination: vector.fascination || 0,
      boredom: vector.boredom || 0,
      
      // Legacy: anticipation (map from interest + curiosity for backward compatibility)
      anticipation: (vector.interest || 0) * 0.5 + (vector.curiosity || 0) * 0.5,
      
      // Meta-state
      current_state: data.description || 'Unknown',
      dominant: data.dominant[0],
      valence: data.valence,
      arousal: data.arousal,
      entropy: data.volatility, // Using volatility as entropy proxy
    } as EmotionState;
  }

  /**
   * Get recent memories
   */
  async getRecentMemories(limit: number = 10, user_id?: string): Promise<Memory[]> {
    try {
      // Build query params
      const params = new URLSearchParams({ limit: limit.toString() });
      if (user_id) {
        params.append('user_id', user_id);
      }
      
      const response = await fetch(`${this.baseUrl}/memory/recent?${params.toString()}`);
      
      if (!response.ok) {
        throw new Error(`Failed to fetch memories: ${response.status}`);
      }

      const json = await response.json();
      
      if (!json.success) {
        throw new Error('Failed to retrieve memories');
      }

      return json.memories || [];
    } catch (error) {
      console.error('Error fetching recent memories:', error);
      return []; // Return empty array on error (graceful degradation)
    }
  }

  /**
   * Get active goals
   */
  async getActiveGoals(): Promise<Goal[]> {
    try {
      const response = await fetch(`${this.baseUrl}/goal/active`);
      
      if (!response.ok) {
        throw new Error(`Failed to fetch goals: ${response.status}`);
      }

      const json = await response.json();
      
      if (!json.success) {
        throw new Error('Failed to retrieve goals');
      }

      return json.goals || [];
    } catch (error) {
      console.error('Error fetching active goals:', error);
      return [];
    }
  }

  /**
   * Get goal context (active goals + current focus)
   */
  async getGoalContext(): Promise<GoalContext> {
    try {
      const response = await fetch(`${this.baseUrl}/goal/context`);
      
      if (!response.ok) {
        throw new Error(`Failed to fetch goal context: ${response.status}`);
      }

      const json = await response.json();
      
      if (!json.success) {
        throw new Error('Failed to retrieve goal context');
      }

      return json.context;
    } catch (error) {
      console.error('Error fetching goal context:', error);
      return { active_goals: [], current_focus: null, pending_proposals: [] };
    }
  }

  /**
   * Generate a new goal on demand
   */
  async generateGoal(trigger: string = 'user_requested', context?: Record<string, unknown>): Promise<Goal | null> {
    try {
      const response = await fetch(`${this.baseUrl}/goal/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          trigger,
          context: context || {},
        }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to generate goal: ${response.status}`);
      }

      const json = await response.json();
      
      if (!json.success) {
        throw new Error('Failed to generate goal');
      }

      return json.goal || null;
    } catch (error) {
      console.error('Error generating goal:', error);
      return null;
    }
  }

  /**
   * Pursue a goal autonomously through multiple L2/L3 iterations
   */
  async pursueGoal(
    goalId: string,
    loopCount: number,
    toolPermissions: string[] = [],
    allowInterruption: boolean = true
  ): Promise<{
    success: boolean;
    goal_id: string;
    goal_name: string;
    iterations: Array<{ iteration: number; l3_response: string; progress: number }>;
    progress_updates: Array<{ iteration: number; progress: number; response: string }>;
    initial_progress: number;
    final_progress: number;
    progress_delta: number;
    loop_count: number;
    message: string;
  } | null> {
    try {
      const response = await fetch(`${this.baseUrl}/goal/pursue`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          goal_id: goalId,
          loop_count: loopCount,
          tool_permissions: toolPermissions,
          allow_interruption: allowInterruption,
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `Request failed with status ${response.status}`);
      }
      const json = await response.json();
      if (!json.success) {
        throw new Error(json.message || 'Failed to pursue goal');
      }
      return json;
    } catch (error) {
      console.error('Error pursuing goal:', error);
      return null;
    }
  }

  /**
   * Delete a goal by ID
   */
  async deleteGoal(goalId: string): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/goal/${goalId}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `Request failed with status ${response.status}`);
      }
      const json = await response.json();
      return json.success || false;
    } catch (error) {
      console.error('Error deleting goal:', error);
      return false;
    }
  }

  /**
   * Get system status
   */
  async getSystemStatus(): Promise<{ healthy: boolean; database: boolean }> {
    try {
      const response = await fetch(`${this.baseUrl}/health`);
      const data = await response.json();
      
      return {
        healthy: response.ok,
        database: data.database === 'connected',
      };
    } catch (error) {
      console.error('Failed to fetch system status:', error);
      return {
        healthy: false,
        database: false,
      };
    }
  }

  /**
   * Get system state machine status (Sleep/Wake cycle)
   */
  async getSystemState(): Promise<SystemStateResponse> {
    const response = await fetch(`${this.baseUrl}/system/state`);
    if (!response.ok) {
      throw new Error(`Failed to fetch system state: ${response.status}`);
    }
    return response.json();
  }

  /**
   * Trigger a soft backend restart.
   *
   * Backend will exit the process; Docker restart policy should respawn it.
   */
  async restartSystem(): Promise<{ status: string; message: string }> {
    const response = await fetch(`${this.baseUrl}/system/restart`, {
      method: 'POST',
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `Restart request failed with status ${response.status}`);
    }
    return response.json();
  }

  /**
   * Force system into DREAMING -> SLEEPING
   */
  async sleepSystem(userId: string = 'default'): Promise<SystemStateResponse> {
    const response = await fetch(`${this.baseUrl}/system/state/sleep`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `Sleep request failed with status ${response.status}`);
    }
    return response.json();
  }

  /**
   * Force system wake to ACTIVE (returns greeting + state)
   */
  async wakeSystem(userId: string = 'default'): Promise<WakeSystemResponse> {
    const response = await fetch(`${this.baseUrl}/system/state/wake`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `Wake request failed with status ${response.status}`);
    }
    return response.json();
  }

  /**
   * Create WebSocket connection for real-time updates
   */
  createEmotionWebSocket(): WebSocket {
    const wsUrl = this.baseUrl.replace(/^http/, 'ws');
    return new WebSocket(`${wsUrl}/ws/emotion`);
  }

  /**
   * Get memory graph data for visualization.
   * Returns nodes and links from the /memory/graph endpoint.
   */
  async getMemoryGraph(): Promise<{
    nodes: Array<{ id: string; label: string; group: string; content: string }>;
    links: Array<{ source: string; target: string; value: number }>;
  }> {
    const response = await fetch(`${this.baseUrl}/memory/graph`);

    if (!response.ok) {
      // Try to read the backend error detail for better diagnostics
      let detail = `HTTP ${response.status}`;
      try {
        const errBody = await response.json();
        if (errBody.detail) detail = errBody.detail;
      } catch {}
      throw new Error(`Failed to fetch memory graph: ${detail}`);
    }

    const json = await response.json();
    return {
      nodes: json.nodes || [],
      links: json.links || [],
    };
  }
}

// Export singleton instance
export const auraApi = new AuraApiService();

export default auraApi;


// ---------------------------------------------------------------------------
// B1-07: agenda, owner controls and thumbs. Contract: api/routes/agenda.py, autonomy.py, chat.py.
// ---------------------------------------------------------------------------
export interface AgendaItem {
  id: string; kind: string; content: string; refs: string[]; priority: number; venue?: string | null;
  state: string; source?: string; created_at?: string | null; due_at?: string | null;
  expires_at?: string | null; delivered_at?: string | null; resolved_at?: string | null;
}
/** P2-33 slider: 0 reactive, 1 attentive, 2 proactive, 3 autonomous. */
export type AutonomyLevel = 0 | 1 | 2 | 3;
export interface AutonomyBudgetUse { used: number; limit: number }
export interface AutonomyState {
  level: AutonomyLevel; muted_kinds: string[]; killed: boolean; killed_at: string | null;
  level_name?: string; effective_level?: AutonomyLevel; tier_cap?: number;
  budget?: { day: string; resources: Record<string, AutonomyBudgetUse> } | null;
  quiet_hours?: { start: string | number; end: string | number; active: boolean };
  autonomy_enabled?: boolean; workspace_enabled?: boolean; goals_v2_enabled?: boolean;
}

async function b1Json<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const e: any = new Error(`Request failed (${res.status})`);
    e.status = res.status;
    try { e.detail = (await res.json())?.detail; } catch { /* no body */ }
    throw e;
  }
  return res.json();
}

export const agendaApi = {
  list: async (): Promise<AgendaItem[]> => (await b1Json<{ items: AgendaItem[] }>('/agenda')).items,
  ack: (id: string) => b1Json<AgendaItem>(`/agenda/${encodeURIComponent(id)}/ack`, 'POST'),
  dismiss: (id: string) => b1Json<AgendaItem>(`/agenda/${encodeURIComponent(id)}/dismiss`, 'POST'),
};

export const autonomyApi = {
  get: () => b1Json<AutonomyState>('/autonomy'),
  setLevel: (level: AutonomyLevel) => b1Json<AutonomyState>('/autonomy/level', 'PUT', { level }),
  mute: (kind: string) => b1Json<AutonomyState>('/autonomy/mute', 'POST', { kind }),
  unmute: (kind: string) => b1Json<AutonomyState>('/autonomy/unmute', 'POST', { kind }),
  kill: async (): Promise<AutonomyState> => (await b1Json<{ state: AutonomyState }>('/autonomy/kill', 'POST')).state,
  resume: () => b1Json<AutonomyState>('/autonomy/resume', 'POST'),
};

/** POST /chat/outcome. The route is 404 when the outcome flag is off (error.status === 404). */
export const outcomeApi = {
  send: (messageId: string, signal: 'up' | 'down') =>
    b1Json<{ experience_id: string; signal: string }>('/chat/outcome', 'POST', { message_id: messageId, signal }),
};
