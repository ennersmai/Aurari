'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Terminal, Trash2, Pause, Play, Filter } from 'lucide-react';
import { cn } from '@/lib/utils';

interface LogEntry {
  source: string;
  stream: 'stdout' | 'stderr';
  line: string;
  timestamp: number;
}

const SOURCE_COLORS: Record<string, string> = {
  cosyvoice: 'text-cyan-400',
  docker: 'text-blue-400',
  backend: 'text-green-400',
  database: 'text-purple-400',
  frontend: 'text-yellow-400',
  launcher: 'text-orange-400',
};

const SOURCE_BADGES: Record<string, string> = {
  cosyvoice: 'bg-cyan-900/40 text-cyan-400 border-cyan-800',
  docker: 'bg-blue-900/40 text-blue-400 border-blue-800',
  backend: 'bg-green-900/40 text-green-400 border-green-800',
  database: 'bg-purple-900/40 text-purple-400 border-purple-800',
  frontend: 'bg-yellow-900/40 text-yellow-400 border-yellow-800',
  launcher: 'bg-orange-900/40 text-orange-400 border-orange-800',
};

export default function SystemConsole() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const logsRef = useRef<LogEntry[]>([]);
  const pausedBufferRef = useRef<LogEntry[]>([]);

  // Keep logsRef in sync
  useEffect(() => {
    logsRef.current = logs;
  }, [logs]);

  // Auto-scroll
  useEffect(() => {
    if (!paused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, paused]);

  // Connect to SSE
  useEffect(() => {
    let eventSource: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      try {
        eventSource = new EventSource('http://localhost:9876/logs/stream');

        eventSource.onmessage = (event) => {
          try {
            const entry: LogEntry = JSON.parse(event.data);
            if (paused) {
              pausedBufferRef.current.push(entry);
            } else {
              setLogs((prev) => {
                const next = [...prev, entry];
                // Keep last 2000 lines
                if (next.length > 2000) return next.slice(-2000);
                return next;
              });
            }
          } catch {
            // Ignore malformed JSON
          }
        };

        eventSource.onerror = () => {
          eventSource?.close();
          reconnectTimer = setTimeout(connect, 2000);
        };
      } catch {
        reconnectTimer = setTimeout(connect, 2000);
      }
    };

    connect();

    return () => {
      eventSource?.close();
      clearTimeout(reconnectTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When unpausing, flush the buffer
  const handleTogglePause = useCallback(() => {
    setPaused((prev) => {
      if (prev) {
        // Unpausing — flush buffer
        const buffered = pausedBufferRef.current;
        pausedBufferRef.current = [];
        setLogs((existing) => {
          const next = [...existing, ...buffered];
          if (next.length > 2000) return next.slice(-2000);
          return next;
        });
      }
      return !prev;
    });
  }, []);

  const handleClear = useCallback(() => {
    setLogs([]);
    pausedBufferRef.current = [];
  }, []);

  const filteredLogs = filter
    ? logs.filter((l) => l.source === filter)
    : logs;

  const sources = Array.from(new Set(logs.map((l) => l.source)));

  return (
    <div className="h-full flex flex-col bg-black/60 border border-green-900/30 rounded-lg overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-green-900/30 bg-black/40">
        <Terminal size={14} className="text-green-400" />
        <span className="text-xs font-mono text-green-400 font-bold flex-1">
          SYSTEM CONSOLE
        </span>
        <span className="text-[10px] font-mono text-gray-500">
          {logs.length} lines
        </span>

        {/* Source filter pills */}
        {sources.map((src) => (
          <button
            key={src}
            onClick={() => setFilter(filter === src ? null : src)}
            className={cn(
              'px-2 py-0.5 text-[10px] font-mono rounded border transition-colors',
              filter === src
                ? SOURCE_BADGES[src] || 'bg-gray-900/40 text-gray-400 border-gray-800'
                : 'bg-transparent text-gray-600 border-gray-800 hover:text-gray-400'
            )}
          >
            {src}
          </button>
        ))}

        <button
          onClick={handleTogglePause}
          className="p-1 hover:bg-white/5 rounded transition-colors"
          title={paused ? 'Resume' : 'Pause'}
        >
          {paused ? (
            <Play size={12} className="text-yellow-400" />
          ) : (
            <Pause size={12} className="text-gray-500" />
          )}
        </button>
        <button
          onClick={handleClear}
          className="p-1 hover:bg-white/5 rounded transition-colors"
          title="Clear"
        >
          <Trash2 size={12} className="text-gray-500" />
        </button>
      </div>

      {/* Log lines */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto font-mono text-xs leading-relaxed p-2 space-y-0"
      >
        {filteredLogs.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-600">
            <div className="text-center space-y-2">
              <Terminal size={32} className="mx-auto opacity-30" />
              <p className="text-xs">Waiting for system logs...</p>
              <p className="text-[10px]">
                Connect to <span className="text-green-700">localhost:9876</span>
              </p>
            </div>
          </div>
        )}
        {filteredLogs.map((entry, i) => (
          <div
            key={i}
            className={cn(
              'flex gap-2 hover:bg-white/[0.02] px-1 rounded',
              entry.stream === 'stderr' && 'bg-red-950/10'
            )}
          >
            <span className="text-gray-600 shrink-0 w-16 text-right select-none">
              {new Date(entry.timestamp * 1000).toLocaleTimeString()}
            </span>
            <span
              className={cn(
                'shrink-0 w-20 text-right font-semibold select-none',
                SOURCE_COLORS[entry.source] || 'text-gray-500'
              )}
            >
              [{entry.source}]
            </span>
            <span
              className={cn(
                'break-all whitespace-pre-wrap flex-1',
                entry.stream === 'stderr'
                  ? 'text-red-400'
                  : 'text-gray-300'
              )}
            >
              {entry.line}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
