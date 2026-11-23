import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const reduced = vi.hoisted(() => ({ value: false }));
vi.mock('framer-motion', async () => {
  const R = await import('react');
  const strip = (tag: string) => (props: any) => {
    const { initial, animate, transition, ...rest } = props;
    const extra: Record<string, any> = {};
    if (initial !== undefined) extra['data-initial'] = JSON.stringify(initial);
    return R.createElement(tag, { ...rest, ...extra });
  };
  return {
    useReducedMotion: () => reduced.value,
    motion: { section: strip('section'), div: strip('div') },
  };
});

import { GlassCard, StatTile, GlowLine, Sparkline, Legend, SUBSYSTEMS, accentVar } from './index';

beforeEach(() => { reduced.value = false; });

describe('accent mapping', () => {
  it('maps each subsystem to its css variable', () => {
    for (const s of SUBSYSTEMS) expect(accentVar(s)).toBe(`var(--accent-${s})`);
    expect(SUBSYSTEMS).toHaveLength(6);
  });
});

describe('render', () => {
  it('GlassCard', () => {
    const html = renderToStaticMarkup(<GlassCard title="Hello" accent="goals">body</GlassCard>);
    expect(html).toContain('glass-panel');
    expect(html).toContain('Hello');
    expect(html).toContain('var(--accent-goals)');
  });
  it('StatTile', () => {
    const html = renderToStaticMarkup(
      <StatTile label="Memories" value="12" unit="k" delta={-3} accent="memory" spark={[1, 2, 3]} />);
    expect(html).toContain('Memories');
    expect(html).toContain('tabular-nums');
    expect(html).toContain('<polyline');
  });
  it('Sparkline', () => {
    const html = renderToStaticMarkup(<Sparkline data={[1, 3, 2]} accent="tools" />);
    expect(html).toContain('var(--accent-tools)');
    expect(renderToStaticMarkup(<Sparkline data={[1]} />)).not.toContain('polyline');
  });
  it('Legend', () => {
    const html = renderToStaticMarkup(<Legend items={[{ label: 'A', accent: 'learning' }, { label: 'B', accent: 'decisions' }]} />);
    expect(html).toContain('var(--accent-learning)');
    expect(html).toContain('var(--accent-decisions)');
  });
  it('GlowLine', () => {
    const html = renderToStaticMarkup(
      <GlowLine data={[{ x: 'a', y: 1 }, { x: 'b', y: 2 }]} series={[{ key: 'y', accent: 'emotion' }]} />);
    expect(html).toContain('data-chart="glow-line"');
  });
});

describe('reduced motion', () => {
  it('adds entrance props normally and none when reduced', () => {
    const el = () => (<><GlassCard title="t">x</GlassCard><StatTile label="l" value={1} /></>);
    expect(renderToStaticMarkup(el())).toContain('data-initial');
    reduced.value = true;
    expect(renderToStaticMarkup(el())).not.toContain('data-initial');
    expect(renderToStaticMarkup(<GlowLine data={[]} series={[]} />)).not.toContain('data-initial');
  });
});
