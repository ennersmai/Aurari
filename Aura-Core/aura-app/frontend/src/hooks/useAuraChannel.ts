/**
 * useAuraChannel (B1-07): a /ws/aura client per page. Handlers are keyed by event type.
 * Reconnect with last_seq, seq dedupe, polling fallback and the presence throttle live in
 * services/auraChannel.ts.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { createAuraChannelClient, type AuraChannelClient, type AuraEnvelope, type PresenceState } from '@/services/auraChannel';

export type AuraEventHandler = (ev: AuraEnvelope) => void;

export function useAuraChannel(handlers: Record<string, AuraEventHandler> = {}) {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;
  const clientRef = useRef<AuraChannelClient | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (typeof WebSocket === 'undefined') return;
    const client = createAuraChannelClient({
      onEvent: (ev) => handlersRef.current[ev.type]?.(ev),
      onConnection: setConnected,
    });
    clientRef.current = client;
    client.start();
    return () => { client.stop(); clientRef.current = null; };
  }, []);

  const sendPresence = useCallback((s: PresenceState) => clientRef.current?.sendPresence(s), []);
  return { connected, sendPresence };
}
