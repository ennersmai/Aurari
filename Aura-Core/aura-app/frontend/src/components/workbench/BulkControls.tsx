import React from 'react';

/** Abort all asks for confirmation (injectable for tests); pause and resume do not. */
export function handleAbortAll(onAbortAll: () => void, confirmFn: (m: string) => boolean = (m) => window.confirm(m)) {
  if (confirmFn('Abort ALL running delegations? This cannot be undone.')) onAbortAll();
}

export function BulkControls({ paused, onPause, onResume, onAbortAll, confirmFn }: {
  paused: boolean; onPause: () => void; onResume: () => void; onAbortAll: () => void;
  confirmFn?: (m: string) => boolean;
}) {
  return (
    <div className="flex gap-2 items-center" data-testid="bulk-controls">
      {paused && <span className="text-[10px] text-amber-300 font-mono">PAUSED</span>}
      <button className="glass-btn text-xs" onClick={onPause} disabled={paused}>Pause all</button>
      <button className="glass-btn text-xs" onClick={onResume} disabled={!paused}>Resume all</button>
      <button className="glass-btn text-xs" style={{ color: '#f87171' }} onClick={() => handleAbortAll(onAbortAll, confirmFn)}>Abort all</button>
    </div>
  );
}
