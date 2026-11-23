import React from 'react';
import type { DelegationDiff } from '@/services/delegationService';

export function DiffView({ diff, opencodeUrl }: { diff: DelegationDiff | null; opencodeUrl: string | null }) {
  return (
    <div className="glass-panel p-3 text-xs" data-testid="diff-view">
      <div className="font-mono uppercase text-gray-400 mb-1">Changes</div>
      {diff ? (
        <>
          <div>{diff.files_changed.length} files, <span style={{ color: '#34d399' }}>+{diff.additions}</span> <span style={{ color: '#f87171' }}>-{diff.deletions}</span></div>
          <ul className="font-mono">{diff.files_changed.map((f) => <li key={f}>{f}</li>)}</ul>
          {diff.summary && <p className="text-gray-400">{diff.summary}</p>}
        </>
      ) : <div className="text-gray-500">No diff available.</div>}
      {opencodeUrl && <a className="glass-btn text-xs inline-block mt-2" href={opencodeUrl} target="_blank" rel="noreferrer">Open in OpenCode</a>}
    </div>
  );
}
