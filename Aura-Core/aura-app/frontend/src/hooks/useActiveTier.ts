/**
 * useActiveTier: the active tier name (lean, core, titan) from GET /system/tiers (P2-04).
 */
import { useEffect, useState } from 'react';
import { API_BASE_URL } from '@/config';
import type { TiersResponse } from '@/types/inference';

export function activeTierName(data: Pick<TiersResponse, 'active_index' | 'tiers'> | null | undefined): string | null {
  if (!data) return null;
  const found = data.tiers.find((t) => t.index === data.active_index);
  return found ? found.name : null;
}

export function useActiveTier(): string | null {
  const [tier, setTier] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE_URL}/system/tiers`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive) setTier(activeTierName(d)); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  return tier;
}
