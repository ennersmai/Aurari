import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';
import { motion } from 'framer-motion';

export interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  group: string;
  content: string;
}

export interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  value: number;
}

interface MemoryGraphProps {
  nodes: GraphNode[];
  links: GraphLink[];
  width?: number;
  height?: number;
}

const COLORS: Record<string, string> = {
  core: '#f59e0b', // amber-500
  episodic: '#3b82f6', // blue-500
  semantic: '#10b981', // emerald-500
  procedural: '#8b5cf6', // violet-500
  default: '#6b7280' // gray-500
};

export default function MemoryGraph({ 
  nodes: initialNodes, 
  links: initialLinks,
  width = 800, 
  height = 600 
}: MemoryGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  
  // React state for positions
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);
  
  // Interaction state
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number, y: number, content: string } | null>(null);
  
  const simulationRef = useRef<d3.Simulation<GraphNode, GraphLink> | null>(null);
  
  useEffect(() => {
    if (!initialNodes.length) return;
    
    // Deep clone to avoid mutating props, and initialize D3 objects
    const simNodes = initialNodes.map(d => ({ ...d }));
    const simLinks = initialLinks.map(d => ({ ...d }));
    
    // Setup D3 Force Simulation
    const simulation = d3.forceSimulation<GraphNode>(simNodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(simLinks)
        .id((d: GraphNode) => d.id)
        .distance(120)
      )
      .force("charge", d3.forceManyBody().strength(-400))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius(24));
      
    simulationRef.current = simulation;
    
    // Update React state on each D3 tick
    simulation.on("tick", () => {
      // Must spread to trigger re-render
      setNodes([...simNodes]);
      setLinks([...simLinks]);
    });
    
    return () => {
      simulation.stop();
    };
  }, [initialNodes, initialLinks, width, height]);
  
  // --- Drag Handling ---
  const handleDragStart = useCallback((e: React.PointerEvent<SVGCircleElement>, node: GraphNode) => {
    if (!simulationRef.current) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    simulationRef.current.alphaTarget(0.3).restart();
    node.fx = node.x;
    node.fy = node.y;
  }, []);

  const handleDrag = useCallback((e: React.PointerEvent<SVGCircleElement>, node: GraphNode) => {
    if (node.fx === undefined || node.fx === null) return;
    if (!svgRef.current) return;
    
    const rect = svgRef.current.getBoundingClientRect();
    node.fx = e.clientX - rect.left;
    node.fy = e.clientY - rect.top;
  }, []);

  const handleDragEnd = useCallback((e: React.PointerEvent<SVGCircleElement>, node: GraphNode) => {
    if (!simulationRef.current) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    simulationRef.current.alphaTarget(0);
    node.fx = null;
    node.fy = null;
  }, []);

  // --- Hover Handling ---
  const handleNodeHover = (e: React.MouseEvent, node: GraphNode) => {
    setHoveredNode(node.id);
    
    if (svgRef.current) {
      const rect = svgRef.current.getBoundingClientRect();
      setTooltip({
        x: e.clientX - rect.left + 15,
        y: e.clientY - rect.top + 15,
        content: node.content || node.label
      });
    }
  };

  const handleNodeLeave = () => {
    setHoveredNode(null);
    setTooltip(null);
  };

  // Determine which links are connected to the hovered node
  const isLinkConnected = (link: GraphLink) => {
    if (!hoveredNode) return false;
    const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
    const targetId = typeof link.target === 'object' ? link.target.id : link.target;
    return sourceId === hoveredNode || targetId === hoveredNode;
  };

  return (
    <div className="relative" style={{ width, height }}>
      <svg 
        ref={svgRef} 
        width={width} 
        height={height} 
        className="bg-slate-50 dark:bg-slate-900 rounded-xl overflow-hidden border border-slate-200 dark:border-slate-800"
      >
        <g className="links">
          {links.map((link, i) => {
            const source = link.source as GraphNode;
            const target = link.target as GraphNode;
            
            if (source.x === undefined || target.x === undefined) return null;
            
            const isConnected = isLinkConnected(link);
            const baseOpacity = link.value ? Math.max(0.2, link.value) : 0.5;
            const opacity = hoveredNode 
              ? (isConnected ? baseOpacity : 0.05) 
              : baseOpacity;
              
            return (
              <motion.line
                key={`link-${i}`}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke="#94a3b8"
                strokeWidth={hoveredNode && isConnected ? 2 : 1}
                animate={{ opacity }}
                transition={{ duration: 0.2 }}
              />
            );
          })}
        </g>
        
        <g className="nodes">
          {nodes.map((node) => {
            if (node.x === undefined || node.y === undefined) return null;
            
            const color = COLORS[node.group] || COLORS.default;
            const isHovered = hoveredNode === node.id;
            
            let opacity = 1;
            if (hoveredNode && !isHovered) {
              const isConnected = links.some(l => 
                ((typeof l.source === 'object' ? l.source.id : l.source) === hoveredNode && (typeof l.target === 'object' ? l.target.id : l.target) === node.id) ||
                ((typeof l.target === 'object' ? l.target.id : l.target) === hoveredNode && (typeof l.source === 'object' ? l.source.id : l.source) === node.id)
              );
              if (!isConnected) opacity = 0.2;
            }

            return (
              <motion.g 
                key={`node-${node.id}`}
                transform={`translate(${node.x}, ${node.y})`}
                animate={{ opacity }}
                transition={{ duration: 0.2 }}
              >
                <circle
                  r={isHovered ? 14 : 10}
                  fill={color}
                  stroke={isHovered ? "#334155" : "#fff"}
                  strokeWidth={2}
                  className="cursor-grab active:cursor-grabbing drop-shadow-sm"
                  onPointerDown={(e) => handleDragStart(e, node)}
                  onPointerMove={(e) => handleDrag(e, node)}
                  onPointerUp={(e) => handleDragEnd(e, node)}
                  onPointerCancel={(e) => handleDragEnd(e, node)}
                  onMouseEnter={(e) => handleNodeHover(e, node)}
                  onMouseLeave={handleNodeLeave}
                />
              </motion.g>
            );
          })}
        </g>
      </svg>
      
      {/* Tooltip rendered outside SVG for standard HTML positioning */}
      {tooltip && (
        <div 
          className="absolute z-10 p-3 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-xl rounded-lg text-sm max-w-sm pointer-events-none"
          style={{ 
            left: Math.min(tooltip.x, width - 250), // Prevent overflowing right edge
            top: tooltip.y,
            transform: 'translate(0, -50%)'
          }}
        >
          <div className="text-slate-800 dark:text-slate-200 break-words whitespace-pre-wrap">
            {tooltip.content}
          </div>
        </div>
      )}
    </div>
  );
}
