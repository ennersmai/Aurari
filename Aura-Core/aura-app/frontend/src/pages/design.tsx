import React from 'react';
import Head from 'next/head';
import { GlassCard, StatTile, GlowLine, Legend, SUBSYSTEMS, type Accent } from '../components/ui';

const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const lineData = days.map((x, i) => ({
  x,
  recalls: 40 + Math.round(18 * Math.sin(i / 1.3) + i * 4),
  writes: 22 + Math.round(10 * Math.cos(i / 1.7) + i * 2),
}));

const tiles: Array<{ accent: Accent; label: string; value: string; unit?: string; delta: number; spark: number[] }> = [
  { accent: 'memory', label: 'Memories', value: '12,480', delta: 4.2, spark: [3, 5, 4, 7, 6, 9, 11] },
  { accent: 'emotion', label: 'Valence', value: '0.62', delta: -1.8, spark: [6, 5, 7, 6, 5, 4, 5] },
  { accent: 'goals', label: 'Active goals', value: '7', delta: 0, spark: [4, 4, 5, 5, 6, 6, 7] },
  { accent: 'tools', label: 'Tool calls', value: '348', unit: 'today', delta: 12, spark: [2, 6, 4, 9, 7, 10, 13] },
  { accent: 'learning', label: 'Lessons', value: '93', delta: 6.5, spark: [1, 2, 4, 5, 7, 8, 9] },
  { accent: 'decisions', label: 'Pending', value: '2', delta: -50, spark: [5, 4, 4, 3, 3, 2, 2] },
];

const h2: React.CSSProperties = { fontSize: 14, color: 'var(--text-muted)', fontWeight: 500, marginBottom: 'var(--space-4)' };

export default function DesignPage() {
  return (
    <div className="aura-page" style={{ padding: 'var(--space-7) var(--space-6)' }}>
      <Head><title>Design - Aura</title></Head>
      <main style={{ maxWidth: 1120, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-7)' }}>
        <header>
          <h1 style={{ fontSize: 32, fontWeight: 600, margin: 0 }}>Visual language</h1>
          <p style={{ color: 'var(--text-muted)', marginTop: 'var(--space-2)' }}>
            Tokens and shared components. The data is bright, the labels are muted.
          </p>
        </header>

        <section>
          <h2 style={h2}>Stat tiles</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 'var(--space-4)' }}>
            {tiles.map((t) => <StatTile key={t.accent} {...t} />)}
          </div>
        </section>

        <section>
          <h2 style={h2}>Glow lines</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 'var(--space-5)' }}>
            <GlassCard title="Memory activity" accent="memory">
              <GlowLine data={lineData}
                series={[{ key: 'recalls', label: 'Recalls', accent: 'memory' }, { key: 'writes', label: 'Writes', accent: 'learning' }]} />
              <div style={{ marginTop: 'var(--space-4)' }}>
                <Legend items={[{ label: 'Recalls', accent: 'memory' }, { label: 'Writes', accent: 'learning' }]} />
              </div>
            </GlassCard>
            <GlassCard title="Mood and goals" accent="emotion">
              <GlowLine data={lineData}
                series={[{ key: 'writes', label: 'Valence', accent: 'emotion' }, { key: 'recalls', label: 'Progress', accent: 'goals' }]} />
              <div style={{ marginTop: 'var(--space-4)' }}>
                <Legend items={[{ label: 'Valence', accent: 'emotion' }, { label: 'Progress', accent: 'goals' }]} />
              </div>
            </GlassCard>
          </div>
        </section>

        <section>
          <h2 style={h2}>Glass cards</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 'var(--space-5)' }}>
            {SUBSYSTEMS.map((s) => (
              <GlassCard key={s} title={s} accent={s}>
                <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 14, lineHeight: 1.6 }}>
                  Accent <span style={{ color: `var(--accent-${s})` }}>--accent-{s}</span> on a glass panel.
                </p>
              </GlassCard>
            ))}
            <GlassCard title="No accent"><p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 14 }}>Plain card.</p></GlassCard>
          </div>
        </section>

        <section>
          <h2 style={h2}>Legend and typography</h2>
          <GlassCard>
            <Legend items={SUBSYSTEMS.map((s) => ({ label: s, accent: s }))} />
            <div style={{ marginTop: 'var(--space-5)' }}>
              <div style={{ fontSize: 32, fontWeight: 600 }}>Heading 32</div>
              <div style={{ fontSize: 18, marginTop: 'var(--space-2)' }}>Body 18, bright text for the data that matters.</div>
              <div style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 'var(--space-2)' }}>Label 14, muted text for context and captions.</div>
              <div className="tabular-nums" style={{ fontSize: 14, marginTop: 'var(--space-2)' }}>1,111.11 / 8,888.88 (tabular numbers line up)</div>
            </div>
          </GlassCard>
        </section>
      </main>
    </div>
  );
}
