import React from 'react';
import { Chip, Tooltip } from '@mui/material';
import PsychologyIcon from '@mui/icons-material/Psychology';

export interface TurnMetaLike {
  deep_reasoning: boolean;
  tier: string;
  route: string | null;
}

export function capitalize(name: string): string {
  return name ? name.charAt(0).toUpperCase() + name.slice(1) : name;
}

/** Tooltip text for a deep-reasoning turn, e.g. "thought deeply (Core, route think)". */
export function deepReasoningTooltip(meta: TurnMetaLike): string {
  const parts = [capitalize(meta.tier)];
  if (meta.route) parts.push(`route ${meta.route}`);
  return `thought deeply (${parts.join(', ')})`;
}

/** Subtle marker on an assistant message when that turn used deep reasoning (P2-42). */
export function DeepReasoningMarker({ meta }: { meta?: TurnMetaLike | null }) {
  if (!meta || !meta.deep_reasoning) return null;
  return (
    <Tooltip title={deepReasoningTooltip(meta)}>
      <PsychologyIcon
        data-testid="deep-reasoning-marker"
        sx={{ fontSize: 14, ml: 0.75, color: 'rgba(192, 156, 88, 0.6)' }}
      />
    </Tooltip>
  );
}

/** Read-only chip with the active tier name. Click opens the tier view. */
export function TierChip({ tier, onClick }: { tier: string | null; onClick?: () => void }) {
  if (!tier) return null;
  return (
    <Tooltip title="Active tier. Change it in Mission Control.">
      <Chip
        data-testid="tier-chip"
        size="small"
        label={capitalize(tier)}
        onClick={onClick}
        sx={{
          height: 24,
          fontSize: '0.7rem',
          color: 'rgba(192, 156, 88, 0.9)',
          background: 'rgba(192,156,88,0.08)',
          border: '1px solid rgba(192,156,88,0.2)',
          borderRadius: '8px',
        }}
      />
    </Tooltip>
  );
}
