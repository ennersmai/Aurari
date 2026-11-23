import React, { useState } from 'react';

export const GUIDANCE_MAX = 4000;

export function GuidanceBox({ running, onSend }: { running: boolean; onSend: (text: string) => void | Promise<void> }) {
  const [text, setText] = useState('');
  const can = running && text.trim().length > 0 && text.length <= GUIDANCE_MAX;
  return (
    <div className="glass-panel p-3 flex flex-col gap-1" data-testid="guidance-box">
      <textarea className="bg-transparent text-xs border border-white/10 rounded p-2" rows={3}
        maxLength={GUIDANCE_MAX} disabled={!running} value={text}
        placeholder={running ? 'Send guidance to the running task' : 'Guidance is only available while the task is running'}
        onChange={(e) => setText(e.target.value)} />
      <div className="flex justify-between items-center text-[10px] text-gray-500">
        <span className="guidance-counter">{text.length} / {GUIDANCE_MAX}</span>
        <button className="glass-btn text-xs" disabled={!can}
          onClick={async () => { await onSend(text); setText(''); }}>Send</button>
      </div>
    </div>
  );
}
