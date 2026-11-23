import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect } from 'vitest';
import { TierChip, DeepReasoningMarker, deepReasoningTooltip } from './TurnMarkers';
import { activeTierName } from '@/hooks/useActiveTier';
import { buildChatRequestBody } from '@/services/auraApiService';

const tiersFixture = {
  active_index: 1,
  tiers: [
    { index: 0, name: 'lean' },
    { index: 1, name: 'core' },
    { index: 2, name: 'titan' },
  ],
} as any;

describe('P2-42 tier chip', () => {
  it('renders the active tier from the /system/tiers fixture', () => {
    const html = renderToStaticMarkup(<TierChip tier={activeTierName(tiersFixture)} />);
    expect(html).toContain('Core');
    expect(html).toContain('tier-chip');
  });
  it('renders nothing before the tier is known', () => {
    expect(renderToStaticMarkup(<TierChip tier={null} />)).toBe('');
  });
});

describe('P2-42 deep reasoning marker', () => {
  const meta = { deep_reasoning: true, tier: 'core', route: 'think' };
  it('renders with its tooltip text', () => {
    const html = renderToStaticMarkup(<DeepReasoningMarker meta={meta} />);
    expect(html).toContain('deep-reasoning-marker');
    expect(html).toContain('thought deeply (Core, route think)');
  });
  it('omits the route when it is null', () => {
    expect(deepReasoningTooltip({ ...meta, route: null })).toBe('thought deeply (Core)');
  });
  it('renders nothing when the turn did not reason deeply', () => {
    expect(renderToStaticMarkup(<DeepReasoningMarker meta={{ ...meta, deep_reasoning: false }} />)).toBe('');
    expect(renderToStaticMarkup(<DeepReasoningMarker meta={undefined} />)).toBe('');
  });
});

describe('P2-42 chat request body', () => {
  it('has none of the old reasoning fields', () => {
    for (const stream of [true, false]) {
      const body = buildChatRequestBody({ message: 'hi', context_limit: 50 }, stream);
      for (const k of ['reasoning_enabled', 'l2_reasoning_enabled', 'deep_analysis_enabled', 'enable_l2', 'enable_l2_analysis']) {
        expect(body).not.toHaveProperty(k);
      }
      expect(body.message).toBe('hi');
    }
  });
});
