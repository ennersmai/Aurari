export const SUBSYSTEMS = ['memory', 'emotion', 'goals', 'tools', 'learning', 'decisions'] as const;
export type Accent = (typeof SUBSYSTEMS)[number];

/** CSS variable reference for a subsystem accent. Defaults to memory. */
export function accentVar(accent?: Accent): string {
  return `var(--accent-${accent ?? 'memory'})`;
}

/** Props for a subtle entrance; empty when reduced motion is on. */
export function entranceProps(reduced: boolean | null) {
  if (reduced) return {};
  return {
    initial: { opacity: 0, y: 6 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.35, ease: 'easeOut' as const },
  };
}

export type Series = { key: string; label?: string; accent?: Accent };
