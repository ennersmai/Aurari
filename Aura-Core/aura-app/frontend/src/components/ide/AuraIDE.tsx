/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import Editor, { type Monaco } from "@monaco-editor/react";
import type { editor as MonacoEditor } from "monaco-editor";
import { motion, AnimatePresence } from "framer-motion";
import {
  FolderOpen, File, ChevronDown, ChevronRight, RefreshCw,
  Brain, Heart, Zap, Terminal, Send, Play, Square,
  Loader2, Code2,
  GitCompare, MessageSquare, Activity,
  AlertTriangle, ThumbsUp, ThumbsDown, ChevronUp, Wifi,
  WifiOff, RotateCcw, Cpu, History,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE_URL } from "@/config";
import TaskTimeline, { type TimelineStep } from "./TaskTimeline";

// ============================================================================
// TYPES
// ============================================================================

interface FileNode {
  name: string;
  path: string;
  type: "file" | "directory";
  size?: number;
  modified?: number;
  children?: FileNode[];
  truncated?: boolean;
  error?: string;
}

interface TaskData {
  task_id: string;
  goal: string;
  status: string;
  current_step_index: number;
  steps: TaskStep[];
  workspace_path: string;
  task_memory_namespace: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  resonance_scores: number[];
  blocker: string | null;
  blocker_info: BlockerInfo | null;
  file_annotations: Record<string, any[]>;
  file_versions: Record<string, any[]>;
}

interface TaskStep {
  step_number: number;
  step_type: string;
  title: string;
  detail: string;
  tool_name?: string;
  tool_args?: Record<string, any>;
  result?: string;
  success: boolean;
  duration_ms: number;
  timestamp: number;
  emotional_state_snapshot?: EmotionalSnapshot | null;
  active_file?: string | null;
}

interface EmotionalSnapshot {
  dominant_emotion: string;
  valence: number;
  arousal: number;
  top_emotions: Record<string, number>;
}

interface BlockerInfo {
  type: "repeated_failure" | "reasoning_loop" | "step_limit" | "manual";
  tool: string | null;
  attempts: number;
  last_error: string;
  last_reasoning: string;
  suggested_action: string;
}

interface AgentSSEEvent {
  type?: string;
  task_id?: string;
  step?: number;
  step_type?: string;
  title?: string;
  detail?: string;
  tool_name?: string;
  tool_args?: Record<string, any>;
  result?: string;
  success?: boolean;
  duration_ms?: number;
  timestamp?: number;
  emotional_state_snapshot?: EmotionalSnapshot | null;
  active_file?: string | null;
}

interface HeartbeatData {
  task_id: string;
  step: number;
  uptime_s: number;
  memory_used_mb: number;
}

interface IdeChatMessage {
  role: string;
  content: string;
  timestamp?: string;
  file_context?: string;
}

interface FileAnnotation {
  line?: number;
  text: string;
  reasoning: string;
  timestamp: string;
}

// ============================================================================
// DIFF UTILITY — Myers-like line diff for delta patching
// ============================================================================

interface EditOp {
  range: { startLineNumber: number; startColumn: number; endLineNumber: number; endColumn: number };
  text: string;
}

function computeLineEdits(oldText: string, newText: string): EditOp[] {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const edits: EditOp[] = [];

  // Simple LCS-based diff for line-level changes
  const m = oldLines.length;
  const n = newLines.length;

  // Build LCS table (optimized for reasonable file sizes)
  const maxSize = 5000;
  if (m * n > maxSize * maxSize) {
    // File too large for diff — fall back to full replace
    return [{
      range: { startLineNumber: 1, startColumn: 1, endLineNumber: m, endColumn: (oldLines[m - 1]?.length || 0) + 1 },
      text: newText,
    }];
  }

  // Compute LCS matrix
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // Backtrack to find edit operations
  interface DiffChunk { type: "keep" | "delete" | "insert"; oldStart: number; oldEnd: number; newStart: number; newEnd: number }
  const chunks: DiffChunk[] = [];
  let i = m, j = n;
  const ops: Array<{ type: "keep" | "delete" | "insert"; oldIdx: number; newIdx: number }> = [];

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      ops.push({ type: "keep", oldIdx: i, newIdx: j });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.push({ type: "insert", oldIdx: i, newIdx: j });
      j--;
    } else {
      ops.push({ type: "delete", oldIdx: i, newIdx: j });
      i--;
    }
  }
  ops.reverse();

  // Merge consecutive delete/insert ops into edit ranges
  let editIdx = 0;
  while (editIdx < ops.length) {
    const op = ops[editIdx];
    if (op.type === "keep") {
      editIdx++;
      continue;
    }

    // Collect consecutive non-keep ops
    let delStart = -1, delEnd = -1;
    const insertLines: string[] = [];

    while (editIdx < ops.length && ops[editIdx].type !== "keep") {
      const curr = ops[editIdx];
      if (curr.type === "delete") {
        if (delStart === -1) delStart = curr.oldIdx;
        delEnd = curr.oldIdx;
      } else if (curr.type === "insert") {
        insertLines.push(newLines[curr.newIdx - 1]);
        if (delStart === -1) {
          // Pure insert — position at the old line
          delStart = curr.oldIdx + 1;
          delEnd = curr.oldIdx; // empty range
        }
      }
      editIdx++;
    }

    if (delStart !== -1) {
      const startLine = delStart;
      const endLine = delEnd >= delStart ? delEnd : delStart - 1;
      const endCol = endLine >= 1 && endLine <= m ? (oldLines[endLine - 1]?.length || 0) + 1 : 1;

      edits.push({
        range: {
          startLineNumber: startLine,
          startColumn: 1,
          endLineNumber: endLine >= startLine ? endLine : startLine,
          endColumn: endLine >= startLine ? endCol : 1,
        },
        text: insertLines.join("\n") + (insertLines.length > 0 && endLine >= startLine ? "\n" : ""),
      });
    } else if (insertLines.length > 0) {
      // Pure inserts at end
      edits.push({
        range: { startLineNumber: m + 1, startColumn: 1, endLineNumber: m + 1, endColumn: 1 },
        text: insertLines.join("\n") + "\n",
      });
    }
  }

  return edits;
}

// ============================================================================
// TREE MANIPULATION UTILITIES — surgical delta updates
// ============================================================================

function insertNodeInTree(tree: FileNode, path: string, node: FileNode | null): FileNode {
  if (!node) return tree;
  const parts = path.split(/[/\\]/);
  const parentParts = parts.slice(0, -1);

  function recurse(current: FileNode, depth: number): FileNode {
    if (depth >= parentParts.length) {
      // Insert here
      const children = [...(current.children || [])];
      // Check duplicate
      if (children.some((c) => c.path === node!.path)) return current;
      children.push(node!);
      // Sort: directories first, then alpha
      children.sort((a, b) => {
        if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
      return { ...current, children };
    }
    if (!current.children) return current;
    return {
      ...current,
      children: current.children.map((child) => {
        const childParts = child.path.split(/[/\\]/);
        if (childParts[depth] === parentParts[depth] && child.type === "directory") {
          return recurse(child, depth + 1);
        }
        return child;
      }),
    };
  }

  return recurse(tree, 0);
}

function updateNodeInTree(tree: FileNode, path: string, node: FileNode | null): FileNode {
  if (!node) return tree;
  function recurse(current: FileNode): FileNode {
    if (current.path === path) {
      return { ...current, ...node, children: current.children };
    }
    if (!current.children) return current;
    return { ...current, children: current.children.map(recurse) };
  }
  return recurse(tree);
}

function removeNodeFromTree(tree: FileNode, path: string): FileNode {
  function recurse(current: FileNode): FileNode {
    if (!current.children) return current;
    return {
      ...current,
      children: current.children
        .filter((child) => child.path !== path)
        .map(recurse),
    };
  }
  return recurse(tree);
}

function formatChatTime(timestamp?: string): string {
  if (!timestamp) return "";
  try {
    const d = new Date(timestamp);
    const now = new Date();
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (d.toDateString() !== now.toDateString()) {
      return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
    }
    return time;
  } catch {
    return "";
  }
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

// ============================================================================
// FILE TREE COMPONENT
// ============================================================================

function FileTreeNode({
  node,
  depth,
  activeFile,
  onSelect,
  taskAnnotations,
}: {
  node: FileNode;
  depth: number;
  activeFile: string;
  onSelect: (path: string) => void;
  taskAnnotations: Record<string, any[]>;
}) {
  const [isOpen, setIsOpen] = useState(depth < 2);
  const isDir = node.type === "directory";
  const isActive = node.path === activeFile;
  const hasAnnotation = taskAnnotations[node.path]?.length > 0;

  const ext = node.name.split(".").pop()?.toLowerCase() || "";
  const langColors: Record<string, string> = {
    py: "text-yellow-400",
    ts: "text-blue-400",
    tsx: "text-blue-300",
    js: "text-yellow-300",
    jsx: "text-yellow-200",
    json: "text-green-400",
    md: "text-gray-400",
    css: "text-pink-400",
    html: "text-orange-400",
    sql: "text-cyan-400",
    yml: "text-red-300",
    yaml: "text-red-300",
    toml: "text-orange-300",
    sh: "text-green-300",
  };

  return (
    <div>
      <button
        onClick={() => {
          if (isDir) setIsOpen(!isOpen);
          else onSelect(node.path);
        }}
        className={cn(
          "w-full flex items-center gap-1.5 px-2 py-1 text-left text-xs font-mono transition-colors rounded-sm",
          isActive
            ? "bg-amber-900/30 text-amber-200 border-l-2 border-amber-500"
            : "hover:bg-white/5 text-gray-400 hover:text-gray-200",
          hasAnnotation && !isActive && "text-amber-400/80",
        )}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
      >
        {isDir ? (
          isOpen ? <ChevronDown size={12} className="text-gray-600 flex-shrink-0" /> : <ChevronRight size={12} className="text-gray-600 flex-shrink-0" />
        ) : (
          <span className="w-3 flex-shrink-0" />
        )}
        {isDir ? (
          <FolderOpen size={13} className="text-amber-600 flex-shrink-0" />
        ) : (
          <File size={13} className={cn("flex-shrink-0", langColors[ext] || "text-gray-500")} />
        )}
        <span className="truncate">{node.name}</span>
        {hasAnnotation && (
          <div className="w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0 ml-auto" />
        )}
      </button>

      {isDir && isOpen && node.children && (
        <div>
          {node.children.map((child) => (
            <FileTreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              activeFile={activeFile}
              onSelect={onSelect}
              taskAnnotations={taskAnnotations}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// TERMINAL PANEL
// ============================================================================

function TerminalPanel({
  steps,
  isExpanded,
  onToggle,
}: {
  steps: TaskStep[];
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [steps]);

  // Filter to execution-relevant steps
  const terminalSteps = steps.filter(
    (s) => ["tool_call", "tool_result", "error", "complete"].includes(s.step_type)
  );

  return (
    <div className={cn(
      "border-t border-amber-900/30 bg-black/60 transition-all",
      isExpanded ? "h-64" : "h-8",
    )}>
      <button
        onClick={onToggle}
        className="w-full h-8 px-3 flex items-center justify-between text-xs font-mono text-amber-500 hover:bg-amber-900/10 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Terminal size={12} />
          <span>TERMINAL</span>
          {terminalSteps.length > 0 && (
            <span className="text-gray-600">({terminalSteps.length} outputs)</span>
          )}
        </div>
        {isExpanded ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
      </button>
      {isExpanded && (
        <div ref={scrollRef} className="h-[calc(100%-2rem)] overflow-y-auto p-2 space-y-1 custom-scrollbar">
          {terminalSteps.length === 0 ? (
            <div className="text-gray-600 text-xs font-mono text-center py-4">
              No execution output yet
            </div>
          ) : (
            terminalSteps.map((step, idx) => (
              <div key={idx} className="text-[11px] font-mono leading-relaxed">
                {step.step_type === "error" ? (
                  <span className="text-red-400">
                    <span className="text-red-600">[ERR]</span> {step.title}: {step.detail}
                  </span>
                ) : step.step_type === "tool_call" ? (
                  <span className="text-amber-400">
                    <span className="text-amber-600">[RUN]</span> {step.tool_name}({step.tool_args ? JSON.stringify(step.tool_args).slice(0, 100) : ""})
                  </span>
                ) : step.step_type === "tool_result" ? (
                  <span className={step.success ? "text-green-400" : "text-red-400"}>
                    <span className={step.success ? "text-green-600" : "text-red-600"}>[{step.success ? "OK" : "FAIL"}]</span>{" "}
                    {step.result?.slice(0, 200) || step.detail}
                    {step.duration_ms > 0 && <span className="text-gray-600 ml-1">({step.duration_ms}ms)</span>}
                  </span>
                ) : step.step_type === "complete" ? (
                  <span className="text-green-400">
                    <span className="text-green-600">[DONE]</span> {step.title}
                  </span>
                ) : null}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// MAIN IDE COMPONENT
// ============================================================================

export default function AuraIDE() {
  // === STATE ===
  const [fileTree, setFileTree] = useState<FileNode | null>(null);
  const [activeFile, setActiveFile] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [diffContent, setDiffContent] = useState<{ current: string; previous: string | null } | null>(null);

  // Task state
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [activeTask, setActiveTask] = useState<TaskData | null>(null);
  const [taskGoalInput, setTaskGoalInput] = useState("");
  const [isCreatingTask, setIsCreatingTask] = useState(false);

  // Agent loop state
  const [agentSteps, setAgentSteps] = useState<TaskStep[]>([]);
  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const [agentTaskId, setAgentTaskId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Aura panel state
  const [emotionState, setEmotionState] = useState<any>(null);
  const [ideChat, setIdeChat] = useState<IdeChatMessage[]>([]);
  const [ideChatInput, setIdeChatInput] = useState("");
  const [showChatHistory, setShowChatHistory] = useState(false);

  // Layout state
  const [terminalExpanded, setTerminalExpanded] = useState(false);
  const [taskAnnotations, setTaskAnnotations] = useState<Record<string, any[]>>({});

  // WebSocket file tree state
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const wsReconnectRef = useRef<number>(0);

  // Heartbeat state
  const [lastHeartbeat, setLastHeartbeat] = useState<number>(0);
  const [heartbeatData, setHeartbeatData] = useState<HeartbeatData | null>(null);
  const [signalLost, setSignalLost] = useState(false);

  // Escalation state
  const [escalation, setEscalation] = useState<BlockerInfo | null>(null);
  const [guidanceInput, setGuidanceInput] = useState("");

  // Replay mode state
  const [isReplayMode, setIsReplayMode] = useState(false);
  const [replayIndex, setReplayIndex] = useState<number | null>(null);
  const [replayFileContent, setReplayFileContent] = useState<string | null>(null);

  // Delta patching refs
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const userEditingRef = useRef(false);
  const userEditTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingDeltaRef = useRef<{ path: string; content: string } | null>(null);

  // Refs
  const chatScrollRef = useRef<HTMLDivElement>(null);

  // === MONACO EDITOR REF CAPTURE ===

  const handleEditorMount = useCallback(
    (editor: MonacoEditor.IStandaloneCodeEditor, monaco: Monaco) => {
      editorRef.current = editor;
      monacoRef.current = monaco;
      // Track user edits for delta queue
      editor.onDidChangeModelContent((e) => {
        if (e.isFlush) return; // Ignore programmatic setValue
        userEditingRef.current = true;
        if (userEditTimerRef.current) clearTimeout(userEditTimerRef.current);
        userEditTimerRef.current = setTimeout(() => {
          userEditingRef.current = false;
          // Apply any queued delta
          if (pendingDeltaRef.current) {
            const { path, content } = pendingDeltaRef.current;
            pendingDeltaRef.current = null;
            applyDeltaPatch(path, content);
          }
        }, 2000);
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // === DELTA PATCHING — apply incoming file writes as edits ===

  const applyDeltaPatch = useCallback(
    (path: string, newContent: string) => {
      // If not the active file, just open it normally
      if (path !== activeFile) {
        setActiveFile(path);
        setFileContent(newContent);
        return;
      }
      // If user is actively editing, queue the delta
      if (userEditingRef.current) {
        pendingDeltaRef.current = { path, content: newContent };
        return;
      }
      const editor = editorRef.current;
      const monaco = monacoRef.current;
      if (!editor || !monaco) {
        setFileContent(newContent);
        return;
      }
      const model = editor.getModel();
      if (!model) {
        setFileContent(newContent);
        return;
      }
      const currentText = model.getValue();
      if (currentText === newContent) return; // No change

      const edits = computeLineEdits(currentText, newContent);
      if (edits.length === 0) return;

      // Apply as model edits — preserves scroll, cursor, selection, undo
      model.pushEditOperations(
        [],
        edits.map((e) => ({
          range: new monaco.Range(
            e.range.startLineNumber,
            e.range.startColumn,
            e.range.endLineNumber,
            e.range.endColumn,
          ),
          text: e.text,
        })),
        () => null,
      );
      // Keep React state in sync
      setFileContent(model.getValue());
    },
    [activeFile],
  );

  // === WEBSOCKET FILE TREE ===

  const connectFileTreeWs = useCallback(() => {
    const wsUrl = API_BASE_URL.replace(/^http/, "ws") + "/workspace/watch";
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      wsReconnectRef.current = 0;
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === "initial_tree") {
          setFileTree(msg.tree);
        } else if (msg.type === "pong") {
          // keepalive
        } else if (msg.type === "created") {
          setFileTree((prev) => {
            if (!prev) return prev;
            return insertNodeInTree(prev, msg.path, msg.node);
          });
        } else if (msg.type === "modified") {
          setFileTree((prev) => {
            if (!prev) return prev;
            return updateNodeInTree(prev, msg.path, msg.node);
          });
          // Pulse annotation if Aura wrote it
          if (msg.aura_written) {
            setTaskAnnotations((prev) => ({
              ...prev,
              [msg.path]: [...(prev[msg.path] || []), { text: "Modified by Aura", timestamp: msg.timestamp }],
            }));
          }
        } else if (msg.type === "deleted") {
          setFileTree((prev) => {
            if (!prev) return prev;
            return removeNodeFromTree(prev, msg.path);
          });
          // Close file if it was active
          if (msg.path === activeFile) {
            setActiveFile("");
            setFileContent("");
          }
        }
      } catch {
        // Ignore parse errors
      }
    };

    ws.onclose = () => {
      setWsConnected(false);
      wsRef.current = null;
      // Exponential backoff reconnect
      const delay = Math.min(1000 * Math.pow(2, wsReconnectRef.current), 30000);
      wsReconnectRef.current += 1;
      setTimeout(connectFileTreeWs, delay);
    };

    ws.onerror = () => {
      ws.close();
    };

    // Keepalive ping every 25s
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send("ping");
      }
    }, 25000);

    return () => {
      clearInterval(pingInterval);
      ws.close();
    };
  }, [activeFile]);

  // === DATA FETCHING ===

  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/tasks`);
      const data = await res.json();
      if (data.tasks) setTasks(data.tasks);
    } catch (err) {
      console.error("Failed to fetch tasks:", err);
    }
  }, []);

  const fetchActiveTask = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/tasks/active`);
      const data = await res.json();
      if (data.task) {
        setActiveTask(data.task);
        if (data.task.steps) setAgentSteps(data.task.steps);
        if (data.task.file_annotations) setTaskAnnotations(data.task.file_annotations);
      }
    } catch (err) {
      console.error("Failed to fetch active task:", err);
    }
  }, []);

  const fetchEmotionState = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/emotion/state`);
      const data = await res.json();
      setEmotionState(data);
    } catch (err) {
      console.error("Failed to fetch emotion:", err);
    }
  }, []);

  const openFile = useCallback(async (path: string) => {
    setActiveFile(path);
    setIsLoadingFile(true);
    setShowDiff(false);
    setIsReplayMode(false);
    setReplayIndex(null);
    try {
      const res = await fetch(`${API_BASE_URL}/workspace/file/${encodeURIComponent(path)}`);
      const data = await res.json();
      if (data.success) {
        setFileContent(data.content);
      }
    } catch (err) {
      console.error("Failed to open file:", err);
      setFileContent(`// Error loading file: ${path}`);
    } finally {
      setIsLoadingFile(false);
    }
  }, []);

  const toggleDiff = useCallback(async () => {
    if (!activeFile) return;
    if (showDiff) {
      setShowDiff(false);
      return;
    }
    try {
      const res = await fetch(`${API_BASE_URL}/workspace/diff/${encodeURIComponent(activeFile)}`);
      const data = await res.json();
      if (data.success) {
        setDiffContent({ current: data.current, previous: data.previous });
        setShowDiff(true);
      }
    } catch (err) {
      console.error("Failed to fetch diff:", err);
    }
  }, [activeFile, showDiff]);

  // === PERSISTENT IDE CHAT ===

  const loadChatHistory = useCallback(async (taskId: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}/workspace/ide-chat/${encodeURIComponent(taskId)}`);
      const data = await res.json();
      if (data.success && data.messages) {
        setIdeChat(data.messages);
      }
    } catch (err) {
      console.error("Failed to load chat history:", err);
    }
  }, []);

  // === TASK MANAGEMENT ===

  const createTask = useCallback(async () => {
    if (!taskGoalInput.trim() || isCreatingTask) return;
    setIsCreatingTask(true);
    try {
      const res = await fetch(`${API_BASE_URL}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: taskGoalInput }),
      });
      const data = await res.json();
      if (data.task) {
        setTaskGoalInput("");
        fetchTasks();
        startAgentLoop(taskGoalInput);
      }
    } catch (err) {
      console.error("Failed to create task:", err);
    } finally {
      setIsCreatingTask(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskGoalInput, isCreatingTask]);

  // === AGENT LOOP ===

  const startAgentLoop = useCallback(async (taskGoal: string) => {
    if (isAgentRunning) return;
    setIsAgentRunning(true);
    setAgentSteps([]);
    setEscalation(null);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_BASE_URL}/agent/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task: taskGoal,
          max_iterations: 15,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Agent run failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event: AgentSSEEvent = JSON.parse(jsonStr);

            if (event.type === "started") {
              setAgentTaskId(event.task_id || null);
            } else if (event.type === "stream_end") {
              // Done
            } else if (event.type === "heartbeat") {
              // Heartbeat handling
              setLastHeartbeat(Date.now());
              setSignalLost(false);
              try {
                const hb: HeartbeatData = JSON.parse(event.detail || "{}");
                setHeartbeatData(hb);
              } catch { /* ignore */ }
            } else if (event.type === "escalation") {
              // Blocker escalation
              try {
                const blocker: BlockerInfo = JSON.parse(event.detail || "{}");
                setEscalation(blocker);
              } catch { /* ignore */ }
            } else if (event.step !== undefined) {
              const step: TaskStep = {
                step_number: event.step || 0,
                step_type: event.type || "thinking",
                title: event.title || "",
                detail: event.detail || "",
                tool_name: event.tool_name,
                tool_args: event.tool_args,
                result: event.result,
                success: event.success ?? true,
                duration_ms: event.duration_ms || 0,
                timestamp: event.timestamp || Date.now() / 1000,
                emotional_state_snapshot: event.emotional_state_snapshot,
                active_file: event.active_file,
              };
              setAgentSteps((prev) => [...prev, step]);

              // Delta patching: if Aura wrote a file, apply as delta edits
              if (step.title === "file_written" && step.tool_args?.path && step.result) {
                applyDeltaPatch(step.tool_args.path, step.result);
              }
            }
          } catch {
            // Skip malformed events
          }
        }
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setAgentSteps((prev) => [
          ...prev,
          {
            step_number: prev.length + 1,
            step_type: "error",
            title: "Connection failed",
            detail: err.message || "Unknown error",
            success: false,
            duration_ms: 0,
            timestamp: Date.now() / 1000,
          },
        ]);
      }
    } finally {
      setIsAgentRunning(false);
      abortRef.current = null;
      fetchActiveTask();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAgentRunning, openFile, fetchActiveTask, applyDeltaPatch]);

  const abortAgent = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    if (agentTaskId) {
      try {
        await fetch(`${API_BASE_URL}/agent/abort/${agentTaskId}`, { method: "POST" });
      } catch { /* best effort */ }
    }
    setIsAgentRunning(false);
  }, [agentTaskId]);

  const approveAction = useCallback(async (approved: boolean) => {
    if (!agentTaskId) return;
    try {
      await fetch(`${API_BASE_URL}/agent/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: agentTaskId, approved }),
      });
    } catch (err) {
      console.error("Approval failed:", err);
    }
  }, [agentTaskId]);

  // === ESCALATION HANDLERS ===

  const sendGuidance = useCallback(async (mode: "guidance" | "change_approach") => {
    if (!guidanceInput.trim() || !agentTaskId) return;
    try {
      await fetch(`${API_BASE_URL}/agent/guidance`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: agentTaskId, guidance: guidanceInput, mode }),
      });
      setEscalation(null);
      setGuidanceInput("");
    } catch (err) {
      console.error("Failed to send guidance:", err);
    }
  }, [guidanceInput, agentTaskId]);

  const abortEscalation = useCallback(async () => {
    setEscalation(null);
    await abortAgent();
  }, [abortAgent]);

  // === IDE CHAT ===

  const sendIdeChat = useCallback(async () => {
    if (!ideChatInput.trim()) return;
    const userMsg = ideChatInput;
    const now = new Date().toISOString();
    setIdeChatInput("");
    const userMessage: IdeChatMessage = { role: "user", content: userMsg, timestamp: now };
    setIdeChat((prev) => [...prev, userMessage]);

    // Persist user message
    if (agentTaskId) {
      fetch(`${API_BASE_URL}/workspace/ide-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg, task_id: agentTaskId, file_context: activeFile }),
      }).catch(() => {});
    }

    try {
      const context = [
        activeFile ? `Currently viewing: ${activeFile}` : "",
        activeTask ? `Active task: ${activeTask.goal}` : "",
      ].filter(Boolean).join("\n");

      const res = await fetch(`${API_BASE_URL}/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: `[IDE Context: ${context}]\n${userMsg}`,
          user_id: "ide_user",
          conversation_history: ideChat.slice(-6).map((m) => ({
            role: m.role === "user" ? "user" : "assistant",
            content: m.content,
          })),
        }),
      });
      const data = await res.json();
      const responseText = data.response || data.message || "...";
      const auraMessage: IdeChatMessage = { role: "aura", content: responseText, timestamp: new Date().toISOString() };
      setIdeChat((prev) => [...prev, auraMessage]);

      // Persist Aura's response
      if (agentTaskId) {
        fetch(`${API_BASE_URL}/workspace/ide-chat/aura`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: responseText, task_id: agentTaskId, file_context: activeFile }),
        }).catch(() => {});
      }
    } catch {
      setIdeChat((prev) => [...prev, { role: "aura", content: "Connection error.", timestamp: new Date().toISOString() }]);
    }
  }, [ideChatInput, activeFile, activeTask, ideChat, agentTaskId]);

  // === REPLAY MODE ===

  const enterReplayMode = useCallback(() => {
    if (!activeTask || activeTask.status !== "complete") return;
    setIsReplayMode(true);
    setReplayIndex(0);
  }, [activeTask]);

  const exitReplayMode = useCallback(() => {
    setIsReplayMode(false);
    setReplayIndex(null);
    setReplayFileContent(null);
    // Restore current file content
    if (activeFile) {
      openFile(activeFile);
    }
  }, [activeFile, openFile]);

  const seekReplay = useCallback((index: number) => {
    if (!activeTask) return;
    setReplayIndex(index);
    const visualSteps = agentSteps.filter((s) => s.step_type !== "heartbeat");
    const step = visualSteps[index];
    if (!step) return;

    // Find file content at this step from file_versions
    if (step.active_file && activeTask.file_versions[step.active_file]) {
      const versions = activeTask.file_versions[step.active_file];
      // Find the version closest to this step
      const closest = versions.reduce((best: any, v: any) => {
        if (v.step_number && v.step_number <= step.step_number) {
          if (!best || v.step_number > best.step_number) return v;
        }
        return best;
      }, null);
      if (closest) {
        setReplayFileContent(closest.content);
        setActiveFile(step.active_file);
      }
    }
  }, [activeTask, agentSteps]);

  // === EFFECTS ===

  // WebSocket file tree connection (replaces polling)
  useEffect(() => {
    const cleanup = connectFileTreeWs();
    return cleanup;
  }, [connectFileTreeWs]);

  // Task + emotion polling (no tree polling — WebSocket handles that)
  useEffect(() => {
    fetchTasks();
    fetchActiveTask();
    fetchEmotionState();

    const taskInterval = setInterval(fetchTasks, 10000);
    const emotionInterval = setInterval(fetchEmotionState, 5000);

    return () => {
      clearInterval(taskInterval);
      clearInterval(emotionInterval);
    };
  }, [fetchTasks, fetchActiveTask, fetchEmotionState]);

  // Load chat history when active task changes
  useEffect(() => {
    if (activeTask?.task_id) {
      loadChatHistory(activeTask.task_id);
    }
  }, [activeTask?.task_id, loadChatHistory]);

  // Chat scroll
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [ideChat]);

  // Heartbeat signal lost detection
  useEffect(() => {
    if (!isAgentRunning) {
      setSignalLost(false);
      return;
    }
    const interval = setInterval(() => {
      if (lastHeartbeat > 0 && Date.now() - lastHeartbeat > 90000) {
        setSignalLost(true);
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [isAgentRunning, lastHeartbeat]);

  // === DERIVED STATE ===

  const hasWaitingStep = agentSteps.some(
    (s) => s.step_type === "waiting" && !agentSteps.some(
      (later) => later.step_number > s.step_number && ["tool_call", "aborted"].includes(later.step_type)
    )
  );

  const currentStepTitle = useMemo(() => {
    if (!isAgentRunning) return null;
    const last = agentSteps[agentSteps.length - 1];
    return last?.title || "Starting...";
  }, [agentSteps, isAgentRunning]);

  const resonanceScore = useMemo(() => {
    if (!activeTask?.resonance_scores?.length) return null;
    return activeTask.resonance_scores[activeTask.resonance_scores.length - 1];
  }, [activeTask]);

  const dominantEmotion = useMemo(() => {
    if (!emotionState?.vector) return "neutral";
    const vector = emotionState.vector;
    let max = 0;
    let dominant = "neutral";
    for (const [key, val] of Object.entries(vector)) {
      if (typeof val === "number" && val > max) {
        max = val;
        dominant = key;
      }
    }
    return dominant;
  }, [emotionState]);

  // Monaco language detection
  const editorLanguage = useMemo(() => {
    const ext = activeFile.split(".").pop()?.toLowerCase() || "";
    const langMap: Record<string, string> = {
      py: "python", ts: "typescript", tsx: "typescript", js: "javascript",
      jsx: "javascript", json: "json", md: "markdown", css: "css",
      html: "html", sql: "sql", yml: "yaml", yaml: "yaml",
      toml: "toml", sh: "shell", ps1: "powershell", rs: "rust",
      go: "go", java: "java", cpp: "cpp", c: "c", txt: "plaintext",
    };
    return langMap[ext] || "plaintext";
  }, [activeFile]);

  // === RENDER ===

  return (
    <div className="h-full flex flex-col bg-[#0a0a0a] text-gray-200 overflow-hidden">

      {/* TASK BAR */}
      <div className="h-10 border-b border-amber-900/30 bg-black/60 flex items-center px-3 gap-3 flex-shrink-0">
        {/* Task input */}
        <div className="flex items-center gap-2 flex-1">
          <Zap size={14} className="text-amber-500" />
          <input
            type="text"
            value={taskGoalInput}
            onChange={(e) => setTaskGoalInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && createTask()}
            placeholder="Give Aura a mission..."
            disabled={isAgentRunning}
            className="flex-1 bg-transparent border-none text-amber-200 placeholder-amber-900/60 focus:outline-none font-mono text-xs disabled:opacity-50"
          />
          {isAgentRunning ? (
            <button
              onClick={abortAgent}
              className="px-3 py-1 rounded border border-red-700/50 bg-red-900/30 text-red-400 hover:bg-red-900/50 transition-colors text-xs font-mono flex items-center gap-1"
            >
              <Square size={10} /> STOP
            </button>
          ) : (
            <button
              onClick={createTask}
              disabled={!taskGoalInput.trim()}
              className="px-3 py-1 rounded border border-amber-700/50 bg-amber-900/30 text-amber-400 hover:bg-amber-900/50 transition-colors text-xs font-mono disabled:opacity-40 flex items-center gap-1"
            >
              <Play size={10} /> GO
            </button>
          )}
        </div>

        {/* Status indicators */}
        <div className="flex items-center gap-3 text-[10px] font-mono text-gray-500 flex-shrink-0">
          {isAgentRunning && (
            <span className="flex items-center gap-1 text-amber-400">
              <Loader2 size={10} className="animate-spin" />
              {currentStepTitle}
            </span>
          )}
          {activeTask && (
            <span className="text-amber-600">
              TASK: {activeTask.status.toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {/* Approval banner */}
      {hasWaitingStep && (
        <div className="h-9 border-b border-yellow-700/50 bg-yellow-900/20 flex items-center justify-between px-4">
          <div className="flex items-center gap-2 text-xs font-mono text-yellow-300">
            <AlertTriangle size={14} /> APPROVAL REQUIRED
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => approveAction(true)}
              className="flex items-center gap-1 px-3 py-1 rounded border border-green-700/50 bg-green-900/30 text-green-400 hover:bg-green-900/50 text-xs font-mono"
            >
              <ThumbsUp size={10} /> APPROVE
            </button>
            <button
              onClick={() => approveAction(false)}
              className="flex items-center gap-1 px-3 py-1 rounded border border-red-700/50 bg-red-900/30 text-red-400 hover:bg-red-900/50 text-xs font-mono"
            >
              <ThumbsDown size={10} /> DENY
            </button>
          </div>
        </div>
      )}

      {/* Escalation banner */}
      <AnimatePresence>
        {escalation && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-b border-red-700/50 bg-gradient-to-r from-red-950/40 to-amber-950/30 overflow-hidden"
          >
            <div className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle size={16} className="text-red-400" />
                <span className="text-sm font-mono font-bold text-red-300">AURA NEEDS YOU</span>
                <span className="text-[9px] font-mono text-red-500 ml-2">
                  {escalation.type === "repeated_failure" ? `${escalation.tool} failed ${escalation.attempts}×` : "Reasoning loop detected"}
                </span>
              </div>
              {escalation.last_error && (
                <div className="text-[10px] font-mono text-red-400/80 mb-1.5 line-clamp-2">
                  Last error: {escalation.last_error}
                </div>
              )}
              {escalation.last_reasoning && (
                <div className="text-[10px] font-mono text-gray-400 mb-2 line-clamp-2">
                  Her reasoning: {escalation.last_reasoning}
                </div>
              )}
              {escalation.suggested_action && (
                <div className="text-[10px] font-mono text-amber-300 bg-amber-900/20 rounded px-2 py-1.5 mb-2">
                  💡 Suggested: {escalation.suggested_action}
                </div>
              )}
              <div className="flex items-center gap-2 mt-2">
                <input
                  type="text"
                  value={guidanceInput}
                  onChange={(e) => setGuidanceInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendGuidance("guidance")}
                  placeholder="Tell her what to do..."
                  className="flex-1 bg-black/40 border border-amber-900/40 rounded px-3 py-2 text-xs font-mono text-amber-200 placeholder-amber-900/50 focus:outline-none focus:border-amber-500"
                />
                <button
                  onClick={() => sendGuidance("guidance")}
                  disabled={!guidanceInput.trim()}
                  className="px-3 py-2 rounded border border-amber-600/50 bg-amber-900/30 text-amber-300 hover:bg-amber-900/50 text-[10px] font-mono font-bold disabled:opacity-40 whitespace-nowrap"
                >
                  GIVE GUIDANCE
                </button>
                <button
                  onClick={() => sendGuidance("change_approach")}
                  disabled={!guidanceInput.trim()}
                  className="px-3 py-2 rounded border border-blue-600/50 bg-blue-900/30 text-blue-300 hover:bg-blue-900/50 text-[10px] font-mono disabled:opacity-40 whitespace-nowrap"
                >
                  CHANGE APPROACH
                </button>
                <button
                  onClick={abortEscalation}
                  className="px-3 py-2 rounded border border-red-700/50 bg-red-900/30 text-red-400 hover:bg-red-900/50 text-[10px] font-mono whitespace-nowrap"
                >
                  ABORT TASK
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Signal lost warning */}
      {signalLost && (
        <div className="h-7 border-b border-red-700/30 bg-red-950/20 flex items-center px-4 gap-2 text-[10px] font-mono">
          <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <span className="text-red-400">SIGNAL LOST — last seen {Math.round((Date.now() - lastHeartbeat) / 1000)}s ago</span>
        </div>
      )}

      {/* MAIN THREE-PANEL LAYOUT */}
      <div className="flex-1 flex overflow-hidden">

        {/* LEFT SIDEBAR — File Tree + Task List */}
        <div className="w-56 border-r border-amber-900/20 bg-black/40 flex flex-col flex-shrink-0 overflow-hidden">

          {/* Task List */}
          <div className="border-b border-amber-900/20">
            <div className="px-3 py-2 flex items-center justify-between">
              <span className="text-[10px] font-mono text-amber-600 font-bold tracking-wider">TASKS</span>
              <button onClick={fetchTasks} className="text-gray-600 hover:text-amber-400 transition-colors">
                <RefreshCw size={10} />
              </button>
            </div>
            <div className="max-h-32 overflow-y-auto custom-scrollbar px-1 pb-1">
              {tasks.length === 0 ? (
                <div className="text-[9px] font-mono text-gray-700 px-2 py-2 text-center">No tasks yet</div>
              ) : (
                tasks.slice(0, 8).map((task) => (
                  <button
                    key={task.task_id}
                    onClick={() => setActiveTask(task)}
                    className={cn(
                      "w-full text-left px-2 py-1.5 rounded text-[10px] font-mono transition-colors",
                      activeTask?.task_id === task.task_id
                        ? "bg-amber-900/20 text-amber-300"
                        : "text-gray-500 hover:text-gray-300 hover:bg-white/5",
                    )}
                  >
                    <div className="flex items-center gap-1.5">
                      <div className={cn(
                        "w-1.5 h-1.5 rounded-full flex-shrink-0",
                        task.status === "running" ? "bg-amber-500 animate-pulse" :
                        task.status === "complete" ? "bg-green-500" :
                        task.status === "failed" ? "bg-red-500" :
                        task.status === "paused" ? "bg-yellow-500" :
                        "bg-gray-600"
                      )} />
                      <span className="truncate">{task.goal.slice(0, 40)}</span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>

          {/* File Tree */}
          <div className="flex-1 overflow-hidden flex flex-col">
            <div className="px-3 py-2 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-mono text-amber-600 font-bold tracking-wider">FILES</span>
                {wsConnected ? (
                  <span className="flex items-center gap-1 text-[8px] font-mono text-green-500">
                    <Wifi size={8} /> LIVE
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-[8px] font-mono text-yellow-500 animate-pulse">
                    <WifiOff size={8} /> RECONNECTING...
                  </span>
                )}
              </div>
              <button onClick={() => { if (wsRef.current) { wsRef.current.close(); } else { connectFileTreeWs(); } }} className="text-gray-600 hover:text-amber-400 transition-colors">
                <RefreshCw size={10} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              {fileTree ? (
                fileTree.children?.map((node) => (
                  <FileTreeNode
                    key={node.path}
                    node={node}
                    depth={0}
                    activeFile={activeFile}
                    onSelect={openFile}
                    taskAnnotations={taskAnnotations}
                  />
                )) || <div className="text-[10px] font-mono text-gray-700 px-3">Empty workspace</div>
              ) : (
                <div className="flex items-center justify-center py-8">
                  <Loader2 size={16} className="text-amber-600 animate-spin" />
                </div>
              )}
            </div>
          </div>
        </div>

        {/* CENTER — Monaco Editor + Terminal */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* Editor Header */}
          <div className="h-8 border-b border-amber-900/20 bg-black/30 flex items-center px-3 gap-2 flex-shrink-0">
            {activeFile ? (
              <>
                <Code2 size={12} className="text-amber-600" />
                <span className="text-xs font-mono text-amber-300 truncate">{activeFile}</span>
                <div className="flex-1" />
                {isReplayMode && (
                  <span className="flex items-center gap-1 text-[9px] font-mono text-purple-400 bg-purple-900/20 border border-purple-700/30 rounded px-2 py-0.5">
                    <RotateCcw size={9} /> REPLAY
                    <button onClick={exitReplayMode} className="ml-1 text-gray-400 hover:text-white">✕</button>
                  </span>
                )}
                <button
                  onClick={toggleDiff}
                  className={cn(
                    "flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-colors",
                    showDiff
                      ? "bg-blue-900/30 text-blue-400 border border-blue-700/40"
                      : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
                  )}
                >
                  <GitCompare size={10} /> DIFF
                </button>
              </>
            ) : (
              <span className="text-xs font-mono text-gray-600">Select a file from the tree</span>
            )}
          </div>

          {/* Editor */}
          <div className="flex-1 overflow-hidden">
            {isLoadingFile ? (
              <div className="flex items-center justify-center h-full">
                <Loader2 size={24} className="text-amber-600 animate-spin" />
              </div>
            ) : activeFile ? (
              <Editor
                height="100%"
                language={editorLanguage}
                value={isReplayMode && replayFileContent !== null ? replayFileContent : fileContent}
                onChange={(value) => { if (!isReplayMode) setFileContent(value || ""); }}
                onMount={handleEditorMount}
                theme="vs-dark"
                options={{
                  fontSize: 13,
                  fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
                  minimap: { enabled: true, scale: 1 },
                  scrollBeyondLastLine: false,
                  lineNumbers: "on",
                  renderWhitespace: "selection",
                  bracketPairColorization: { enabled: true },
                  cursorBlinking: "smooth",
                  cursorSmoothCaretAnimation: "on",
                  smoothScrolling: true,
                  padding: { top: 8 },
                  wordWrap: "on",
                  readOnly: isReplayMode,
                }}
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-gray-700 gap-3">
                <Brain size={48} className="text-amber-800/40" />
                <span className="text-sm font-mono">Aura is ready</span>
                <span className="text-xs font-mono text-gray-800">Give her a mission or select a file</span>
              </div>
            )}
          </div>

          {/* Task Timeline */}
          {agentSteps.length > 0 && (
            <TaskTimeline
              steps={agentSteps as TimelineStep[]}
              resonanceScores={activeTask?.resonance_scores || []}
              createdAt={activeTask?.created_at || new Date().toISOString()}
              completedAt={activeTask?.completed_at || null}
              isLive={isAgentRunning}
              onStepClick={(step) => {
                if (step.active_file) openFile(step.active_file);
              }}
              replayIndex={isReplayMode ? replayIndex : null}
              onReplaySeek={isReplayMode ? seekReplay : undefined}
            />
          )}

          {/* Terminal */}
          <TerminalPanel
            steps={agentSteps}
            isExpanded={terminalExpanded}
            onToggle={() => setTerminalExpanded(!terminalExpanded)}
          />
        </div>

        {/* RIGHT PANEL — Aura's Presence */}
        <div className="w-72 border-l border-amber-900/20 bg-black/40 flex flex-col flex-shrink-0 overflow-hidden">

          {/* Emotion state */}
          <div className="border-b border-amber-900/20 px-3 py-3">
            <div className="flex items-center gap-2 mb-2">
              <Heart size={12} className="text-amber-500" />
              <span className="text-[10px] font-mono text-amber-600 font-bold tracking-wider">EMOTIONAL STATE</span>
            </div>
            <div className="flex items-center gap-2 mb-1">
              <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
              <span className="text-xs font-mono text-amber-300 capitalize">{dominantEmotion}</span>
            </div>
            {emotionState?.description && (
              <p className="text-[10px] font-mono text-gray-500 leading-relaxed">{emotionState.description}</p>
            )}
            {resonanceScore !== null && (
              <div className="mt-2 flex items-center gap-2">
                <span className="text-[9px] font-mono text-gray-600">RESONANCE</span>
                <div className="flex-1 h-1.5 rounded-full bg-gray-800 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-amber-700 to-amber-400 transition-all"
                    style={{ width: `${(resonanceScore ?? 0) * 100}%` }}
                  />
                </div>
                <span className="text-[9px] font-mono text-amber-400">
                  {((resonanceScore ?? 0) * 100).toFixed(0)}%
                </span>
              </div>
            )}
          </div>

          {/* Current task info */}
          {activeTask && (
            <div className="border-b border-amber-900/20 px-3 py-3">
              <div className="flex items-center gap-2 mb-2">
                <Zap size={12} className="text-amber-500" />
                <span className="text-[10px] font-mono text-amber-600 font-bold tracking-wider">CURRENT TASK</span>
                {activeTask.status === "complete" && !isReplayMode && (
                  <button
                    onClick={enterReplayMode}
                    className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded text-[8px] font-mono text-purple-400 border border-purple-700/30 hover:bg-purple-900/20 transition-colors"
                  >
                    <RotateCcw size={8} /> REPLAY
                  </button>
                )}
                {isReplayMode && (
                  <button
                    onClick={exitReplayMode}
                    className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded text-[8px] font-mono text-gray-400 border border-gray-700/30 hover:bg-white/5 transition-colors"
                  >
                    EXIT REPLAY
                  </button>
                )}
              </div>
              <p className="text-[11px] font-mono text-gray-300 leading-relaxed mb-2">
                {activeTask.goal.slice(0, 120)}
              </p>
              <div className="flex items-center justify-between text-[9px] font-mono text-gray-600">
                <span>Step {activeTask.current_step_index}</span>
                <span className={cn(
                  activeTask.status === "running" ? "text-amber-400" :
                  activeTask.status === "complete" ? "text-green-400" :
                  activeTask.status === "failed" ? "text-red-400" :
                  "text-gray-500",
                )}>
                  {activeTask.status.toUpperCase()}
                </span>
              </div>
              {/* Heartbeat vitals */}
              {heartbeatData && isAgentRunning && (
                <div className="mt-2 flex items-center gap-3 text-[8px] font-mono text-gray-500">
                  <span className="flex items-center gap-1">
                    <Cpu size={8} className="text-amber-600" />
                    UPTIME {formatUptime(heartbeatData.uptime_s)}
                  </span>
                  <span>|</span>
                  <span>MEM {heartbeatData.memory_used_mb}MB</span>
                </div>
              )}
              {/* Replay step info */}
              {isReplayMode && replayIndex !== null && (
                <div className="mt-2 text-[9px] font-mono text-purple-400 bg-purple-900/20 rounded px-2 py-1">
                  Step {replayIndex + 1} / {agentSteps.filter(s => s.step_type !== "heartbeat").length}
                  {(() => {
                    const vs = agentSteps.filter(s => s.step_type !== "heartbeat");
                    const step = vs[replayIndex];
                    if (step?.emotional_state_snapshot) {
                      return ` — ${step.emotional_state_snapshot.dominant_emotion} (${step.emotional_state_snapshot.valence >= 0 ? "+" : ""}${step.emotional_state_snapshot.valence.toFixed(2)})`;
                    }
                    return "";
                  })()}
                </div>
              )}
              {activeTask.blocker && !escalation && (
                <div className="mt-2 text-[9px] font-mono text-yellow-400 bg-yellow-900/20 rounded px-2 py-1">
                  Waiting: {typeof activeTask.blocker === "string" ? activeTask.blocker.slice(0, 100) : "Blocked"}
                </div>
              )}
            </div>
          )}

          {/* Agent steps log (compact) */}
          <div className="border-b border-amber-900/20 px-3 py-2 max-h-40 overflow-y-auto custom-scrollbar">
            <div className="flex items-center gap-2 mb-1.5">
              <Activity size={12} className="text-amber-500" />
              <span className="text-[10px] font-mono text-amber-600 font-bold tracking-wider">STEPS</span>
              <span className="text-[9px] font-mono text-gray-600">{agentSteps.length}</span>
            </div>
            {agentSteps.slice(-8).map((step, idx) => (
              <div key={idx} className="flex items-center gap-1.5 text-[9px] font-mono py-0.5">
                <span className={cn(
                  step.success ? "text-green-600" : "text-red-600",
                )}>
                  {step.success ? "✓" : "✗"}
                </span>
                <span className="text-gray-500 truncate">{step.title}</span>
              </div>
            ))}
            {isAgentRunning && (
              <div className="flex items-center gap-1.5 py-0.5">
                <Loader2 size={8} className="text-amber-400 animate-spin" />
                <span className="text-[9px] font-mono text-amber-400">Processing...</span>
              </div>
            )}
          </div>

          {/* IDE Chat */}
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="px-3 py-2 flex items-center gap-2">
              <MessageSquare size={12} className="text-amber-500" />
              <span className="text-[10px] font-mono text-amber-600 font-bold tracking-wider">ASK AURA</span>
              <button
                onClick={() => setShowChatHistory(!showChatHistory)}
                className={cn(
                  "ml-auto flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-mono transition-colors",
                  showChatHistory
                    ? "bg-amber-900/20 text-amber-400 border border-amber-700/30"
                    : "text-gray-600 hover:text-gray-400",
                )}
              >
                <History size={8} /> {showChatHistory ? "RECENT" : "HISTORY"}
              </button>
            </div>

            <div ref={chatScrollRef} className="flex-1 overflow-y-auto px-3 space-y-2 custom-scrollbar">
              {ideChat.length === 0 && (
                <div className="text-[9px] font-mono text-gray-700 text-center py-4">
                  Ask Aura about what she&apos;s building
                </div>
              )}
              {(showChatHistory ? ideChat : ideChat.slice(-20)).map((msg, idx) => (
                <div key={idx}>
                  <div
                    className={cn(
                      "text-[10px] font-mono rounded px-2 py-1.5 leading-relaxed",
                      msg.role === "user"
                        ? "bg-amber-900/20 text-amber-200 ml-4"
                        : "bg-black/40 text-gray-300 mr-4 border border-amber-900/20",
                    )}
                  >
                    {msg.content}
                  </div>
                  {msg.timestamp && (
                    <div className={cn(
                      "text-[7px] font-mono text-gray-700 mt-0.5",
                      msg.role === "user" ? "text-right mr-1" : "ml-1",
                    )}>
                      {formatChatTime(msg.timestamp)}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="px-3 py-2 border-t border-amber-900/20">
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={ideChatInput}
                  onChange={(e) => setIdeChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendIdeChat()}
                  placeholder="Why did you..."
                  className="flex-1 bg-black/40 border border-amber-900/30 rounded px-2 py-1.5 text-[10px] font-mono text-amber-200 placeholder-amber-900/50 focus:outline-none focus:border-amber-600"
                />
                <button
                  onClick={sendIdeChat}
                  disabled={!ideChatInput.trim()}
                  className="px-2 py-1.5 rounded border border-amber-700/40 bg-amber-900/20 text-amber-400 hover:bg-amber-900/40 transition-colors disabled:opacity-40"
                >
                  <Send size={10} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Custom scrollbar styles */}
      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 5px;
          height: 5px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: #78350f40;
          border-radius: 3px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: #78350f80;
        }
      `}</style>
    </div>
  );
}
