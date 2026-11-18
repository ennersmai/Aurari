import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Share2, RefreshCw, AlertCircle, X, Maximize2, Minimize2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import MemoryGraph, { type GraphNode, type GraphLink } from '@/components/memory/MemoryGraph';
import { auraApi } from '@/services/auraApiService';

interface MemoryGraphDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function MemoryGraphDialog({ open, onClose }: MemoryGraphDialogProps) {
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphLinks, setGraphLinks] = useState<GraphLink[]>([]);
  const [isLoadingGraph, setIsLoadingGraph] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const [graphDims, setGraphDims] = useState({ width: 800, height: 500 });

  const fetchGraph = useCallback(async () => {
    setIsLoadingGraph(true);
    setGraphError(null);
    try {
      const data = await auraApi.getMemoryGraph();
      setGraphNodes(data.nodes);
      setGraphLinks(data.links);
    } catch (error) {
      console.error('Failed to fetch memory graph:', error);
      setGraphError(error instanceof Error ? error.message : 'Failed to load graph');
    } finally {
      setIsLoadingGraph(false);
    }
  }, []);

  // Fetch on open
  useEffect(() => {
    if (open && graphNodes.length === 0) {
      fetchGraph();
    }
  }, [open, fetchGraph, graphNodes.length]);

  // Measure container dimensions
  useEffect(() => {
    if (!open) return;
    const container = graphContainerRef.current;
    if (!container) return;
    const measure = () => {
      const rect = container.getBoundingClientRect();
      const w = Math.max(400, rect.width - 48);
      const h = Math.max(300, rect.height - 24);
      setGraphDims({ width: w, height: h });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    return () => observer.disconnect();
  }, [open, isFullscreen]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (open) window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        key="graph-dialog-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[9999] flex items-center justify-center"
        style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)' }}
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      >
        <motion.div
          key="graph-dialog"
          initial={{ opacity: 0, scale: 0.92, y: 24 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.92, y: 24 }}
          transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
          className="glass-panel flex flex-col overflow-hidden"
          style={{
            width: isFullscreen ? 'calc(100vw - 48px)' : 'min(900px, calc(100vw - 64px))',
            height: isFullscreen ? 'calc(100vh - 48px)' : 'min(650px, calc(100vh - 120px))',
            maxWidth: '100vw',
            maxHeight: '100vh',
            borderRadius: '16px',
            border: '1px solid rgba(255,255,255,0.08)',
            boxShadow: '0 24px 80px rgba(0,0,0,0.5)',
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06] shrink-0">
            <div className="flex items-center gap-3">
              <Share2 size={18} className="text-amber-400" />
              <div>
                <h2 className="text-sm font-mono font-bold tracking-wider text-amber-400/90">
                  MEMORY GRAPH
                </h2>
                <p className="text-[10px] font-mono text-gray-500">
                  {graphNodes.length > 0
                    ? `${graphNodes.length} nodes · ${graphLinks.length} edges`
                    : 'Neural association map'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={fetchGraph}
                disabled={isLoadingGraph}
                className="glass-btn-icon w-8 h-8"
                title="Refresh graph"
              >
                <RefreshCw size={14} className={cn("text-amber-400", isLoadingGraph && "animate-spin")} />
              </button>
              <button
                onClick={() => setIsFullscreen(v => !v)}
                className="glass-btn-icon w-8 h-8"
                title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
              >
                {isFullscreen ? <Minimize2 size={14} className="text-gray-400" /> : <Maximize2 size={14} className="text-gray-400" />}
              </button>
              <button
                onClick={onClose}
                className="glass-btn-icon w-8 h-8"
                title="Close"
              >
                <X size={14} className="text-gray-400" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div ref={graphContainerRef} className="flex-1 overflow-hidden relative">
            {isLoadingGraph && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center space-y-3">
                  <RefreshCw size={32} className="mx-auto text-amber-400 animate-spin" />
                  <p className="text-xs font-mono text-gray-400">Loading memory graph...</p>
                </div>
              </div>
            )}

            {graphError && !isLoadingGraph && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center space-y-4 max-w-sm">
                  <AlertCircle size={36} className="mx-auto text-red-400" />
                  <p className="text-xs font-mono text-red-400">{graphError}</p>
                  <button
                    onClick={fetchGraph}
                    className="glass-btn text-xs px-4 py-2"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}

            {!isLoadingGraph && !graphError && graphNodes.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center space-y-3">
                  <Share2 size={36} className="mx-auto text-amber-800" />
                  <p className="text-xs font-mono text-gray-400">No memory nodes found</p>
                  <p className="text-[10px] font-mono text-gray-600">
                    Memories and their relationships will appear here
                  </p>
                </div>
              </div>
            )}

            {!isLoadingGraph && !graphError && graphNodes.length > 0 && (
              <div className="w-full h-full flex items-center justify-center">
                <MemoryGraph
                  nodes={graphNodes}
                  links={graphLinks}
                  width={graphDims.width}
                  height={graphDims.height}
                />
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-5 py-3 border-t border-white/[0.06] shrink-0">
            <p className="text-[9px] font-mono text-gray-600">
              Drag nodes · Scroll to zoom · Hover for details
            </p>
            <p className="text-[9px] font-mono text-amber-600/60">
              {graphNodes.length > 0 ? `${graphNodes.length} active memories` : 'No data'}
            </p>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
