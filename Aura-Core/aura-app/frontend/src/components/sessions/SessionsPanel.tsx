/**
 * SessionsPanel — full management dialog for sessions (Liquid Glass edition).
 *
 * Tabs:
 *   - "Sessions": list every active/paused session, switch, pause/resume/end
 *   - "New":      create a new SCOPED session (name + optional identity overlay)
 *
 * Identity overlay is the operator's main creative knob here — set
 * `core_values` weights or a `narrative_suffix` to make the agent in this
 * session lean toward a particular character (e.g. "Aura the Engineer").
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import sessionService, {
  CreateSessionPayload,
  IdentityOverlay,
  Session,
  SessionMode,
} from "@/services/sessionService";

interface Props {
  open: boolean;
  onClose: () => void;
  activeSession: Session | null;
  onSelectSession: (session: Session) => void;
  onSessionsChanged?: () => void;
}

type TabValue = "list" | "new";

export default function SessionsPanel({
  open,
  onClose,
  activeSession,
  onSelectSession,
  onSessionsChanged,
}: Props) {
  const [tab, setTab] = useState<TabValue>("list");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newMode, setNewMode] = useState<SessionMode>("scoped");
  const [overlayValuesText, setOverlayValuesText] = useState("");
  const [overlaySuffix, setOverlaySuffix] = useState("");
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await sessionService.list();
      setSessions(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      refresh();
      setNewName("");
      setNewMode("scoped");
      setOverlayValuesText("");
      setOverlaySuffix("");
    }
  }, [open, refresh]);

  const buildOverlay = (): IdentityOverlay | null => {
    const cleanedSuffix = overlaySuffix.trim();
    const lines = overlayValuesText
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    const coreValues: Record<string, number> = {};
    for (const line of lines) {
      const m = line.match(/^([\w\- ]+)\s*[:=]\s*(-?\d+(?:\.\d+)?)$/);
      if (m) coreValues[m[1].trim()] = Number(m[2]);
    }
    if (!cleanedSuffix && Object.keys(coreValues).length === 0) return null;
    return {
      core_values: Object.keys(coreValues).length ? coreValues : null,
      narrative_suffix: cleanedSuffix || null,
    };
  };

  const handleCreate = async () => {
    const trimmed = newName.trim();
    if (!trimmed) {
      setError("Session name is required");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const payload: CreateSessionPayload = {
        name: trimmed,
        mode: newMode,
        identity_overlay: buildOverlay(),
      };
      const session = await sessionService.create(payload);
      await sessionService.start(session.session_id);
      await refresh();
      const fresh = await sessionService.get(session.session_id);
      if (fresh) {
        onSelectSession(fresh);
        onSessionsChanged?.();
      }
      setTab("list");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  const lifecycleAction = async (
    action: "pause" | "resume" | "end",
    sessionId: string,
  ) => {
    setError(null);
    try {
      const fn =
        action === "pause"
          ? sessionService.pause
          : action === "resume"
          ? sessionService.resume
          : sessionService.end;
      await fn.call(sessionService, sessionId);
      await refresh();
      onSessionsChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const visibleSessions = useMemo(
    () => sessions.filter((s) => s.status !== "ended"),
    [sessions],
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      PaperProps={{
        sx: {
          background: 'rgba(18,18,22,0.92)',
          backdropFilter: 'blur(24px) saturate(180%)',
          WebkitBackdropFilter: 'blur(24px) saturate(180%)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: '18px',
          boxShadow: '0 16px 48px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.04) inset',
          overflow: 'hidden',
        },
      }}
    >
      <DialogTitle sx={{
        pb: 1,
        background: 'rgba(255,255,255,0.01)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        <Typography variant="h6" sx={{ fontWeight: 600, letterSpacing: '0.02em' }}>
          Sessions
        </Typography>
        <Typography variant="caption" sx={{ display: "block", opacity: 0.5, mt: 0.5 }}>
          Multiple agents, one Aura. Emotion stays shared across every session.
        </Typography>
      </DialogTitle>

      <Tabs
        value={tab}
        onChange={(_, v: TabValue) => setTab(v)}
        sx={{
          borderBottom: 1,
          borderColor: 'rgba(255,255,255,0.06)',
          px: 2,
          background: 'rgba(255,255,255,0.01)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          '& .MuiTab-root': {
            textTransform: 'none',
            fontSize: '0.78rem',
            fontWeight: 500,
            color: 'rgba(255,255,255,0.45)',
            '&.Mui-selected': { color: '#c09c58' },
          },
          '& .MuiTabs-indicator': {
            backgroundColor: '#c09c58',
            height: 2,
          },
        }}
      >
        <Tab value="list" label="Active sessions" />
        <Tab value="new" label="New session" />
      </Tabs>

      <DialogContent sx={{ minHeight: 360, pt: 2 }}>
        {error && (
          <Alert
            severity="error"
            onClose={() => setError(null)}
            sx={{
              mb: 2,
              background: 'rgba(239,68,68,0.1)',
              border: '1px solid rgba(239,68,68,0.25)',
              backdropFilter: 'blur(8px)',
              borderRadius: '10px',
            }}
          >
            {error}
          </Alert>
        )}

        {tab === "list" && (
          <Box>
            <Box sx={{ display: "flex", justifyContent: "flex-end", mb: 1 }}>
              <Tooltip title="Refresh">
                <span>
                  <IconButton
                    size="small"
                    onClick={refresh}
                    disabled={loading}
                    sx={{
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid rgba(255,255,255,0.06)',
                      borderRadius: '8px',
                      '&:hover': { background: 'rgba(255,255,255,0.07)' },
                    }}
                  >
                    <RefreshIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
            </Box>
            {loading ? (
              <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
                <CircularProgress size={22} sx={{ color: '#c09c58' }} />
              </Box>
            ) : visibleSessions.length === 0 ? (
              <Typography variant="body2" sx={{
                py: 4,
                textAlign: "center",
                color: 'rgba(255,255,255,0.35)',
                fontSize: '0.8rem',
              }}>
                No sessions yet. The Main session is implicit and always present.
              </Typography>
            ) : (
              <List dense disablePadding>
                {visibleSessions.map((s) => {
                  const isActive = activeSession?.session_id === s.session_id;
                  const isMain = sessionService.isMain(s.session_id);
                  return (
                    <ListItem
                      key={s.session_id}
                      disableGutters
                      secondaryAction={
                        <Stack direction="row" spacing={0.5}>
                          {!isMain && s.status === "active" && (
                            <Tooltip title="Pause">
                              <IconButton
                                size="small"
                                onClick={() => lifecycleAction("pause", s.session_id)}
                                sx={{
                                  background: 'rgba(255,255,255,0.03)',
                                  border: '1px solid rgba(255,255,255,0.06)',
                                  borderRadius: '6px',
                                  '&:hover': { background: 'rgba(255,255,255,0.08)' },
                                }}
                              >
                                <PauseIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                          {!isMain && s.status === "paused" && (
                            <Tooltip title="Resume">
                              <IconButton
                                size="small"
                                onClick={() => lifecycleAction("resume", s.session_id)}
                                sx={{
                                  background: 'rgba(255,255,255,0.03)',
                                  border: '1px solid rgba(255,255,255,0.06)',
                                  borderRadius: '6px',
                                  '&:hover': { background: 'rgba(255,255,255,0.08)' },
                                }}
                              >
                                <PlayArrowIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                          {!isMain && (
                            <Tooltip title="End session">
                              <IconButton
                                size="small"
                                onClick={() => lifecycleAction("end", s.session_id)}
                                sx={{
                                  background: 'rgba(239,68,68,0.06)',
                                  border: '1px solid rgba(239,68,68,0.15)',
                                  borderRadius: '6px',
                                  '&:hover': { background: 'rgba(239,68,68,0.12)' },
                                }}
                              >
                                <StopIcon fontSize="small" sx={{ color: '#f87171' }} />
                              </IconButton>
                            </Tooltip>
                          )}
                        </Stack>
                      }
                    >
                      <ListItemButton
                        selected={isActive}
                        onClick={() => onSelectSession(s)}
                        sx={{
                          borderRadius: '10px',
                          pr: 12,
                          mb: 0.5,
                          border: isActive
                            ? '1px solid rgba(192,156,88,0.25)'
                            : '1px solid transparent',
                          background: isActive
                            ? 'rgba(192,156,88,0.08)'
                            : 'transparent',
                          '&:hover': {
                            background: isActive
                              ? 'rgba(192,156,88,0.12)'
                              : 'rgba(255,255,255,0.03)',
                          },
                          transition: 'all 0.15s ease',
                        }}
                      >
                        <ListItemText
                          primary={
                            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {s.name}
                              </Typography>
                              {isMain && (
                                <Chip
                                  label="default"
                                  size="small"
                                  sx={{
                                    height: 18,
                                    fontSize: 9,
                                    background: 'rgba(255,255,255,0.06)',
                                    border: '1px solid rgba(255,255,255,0.08)',
                                    color: 'rgba(255,255,255,0.5)',
                                  }}
                                />
                              )}
                              {isActive && (
                                <CheckCircleIcon fontSize="small" sx={{ color: "#c09c58" }} />
                              )}
                            </Box>
                          }
                          secondary={
                            <Typography
                              variant="caption"
                              component="span"
                              sx={{
                                opacity: 0.55,
                                fontFamily: "monospace",
                                fontSize: '0.65rem',
                              }}
                            >
                              {s.mode} · {s.status} · ns: {s.memory_namespace}
                            </Typography>
                          }
                        />
                      </ListItemButton>
                    </ListItem>
                  );
                })}
              </List>
            )}
          </Box>
        )}

        {tab === "new" && (
          <Stack spacing={2}>
            <TextField
              label="Name"
              placeholder="Research: emotion physics paper"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              autoFocus
              fullWidth
              size="small"
              InputProps={{
                sx: {
                  background: 'rgba(255,255,255,0.03)',
                  borderRadius: '10px',
                  '& fieldset': { borderColor: 'rgba(255,255,255,0.08)' },
                  '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.14)' },
                  '&.Mui-focused fieldset': { borderColor: 'rgba(192,156,88,0.35)' },
                },
              }}
              InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.45)' } }}
            />
            <TextField
              select
              label="Mode"
              value={newMode}
              onChange={(e) => setNewMode(e.target.value as SessionMode)}
              SelectProps={{ native: true }}
              size="small"
              helperText={
                newMode === "ephemeral"
                  ? "Discarded on end. Use for one-off experiments."
                  : "Persists across restarts. Default."
              }
              InputProps={{
                sx: {
                  background: 'rgba(255,255,255,0.03)',
                  borderRadius: '10px',
                  '& fieldset': { borderColor: 'rgba(255,255,255,0.08)' },
                  '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.14)' },
                },
              }}
              InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.45)' } }}
              FormHelperTextProps={{ sx: { color: 'rgba(255,255,255,0.35)', fontSize: '0.65rem' } }}
            >
              <option value="scoped">Scoped (persistent)</option>
              <option value="ephemeral">Ephemeral (temporary)</option>
            </TextField>

            <Divider sx={{ borderColor: 'rgba(255,255,255,0.06)' }}>
              <Chip
                label="Identity overlay (optional)"
                size="small"
                sx={{
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  color: 'rgba(255,255,255,0.45)',
                  fontSize: '0.65rem',
                }}
              />
            </Divider>
            <Typography variant="caption" sx={{ opacity: 0.5, fontSize: '0.7rem' }}>
              Patches Aura's identity at READ time only. Useful for
              &ldquo;Aura the Engineer&rdquo; or &ldquo;Aura the Companion&rdquo; characters.
              Aura's emotion is NOT scoped — it stays shared across sessions.
            </Typography>
            <TextField
              label="Core-value weights"
              placeholder={`precision = 0.95\nwarmth = 0.4`}
              value={overlayValuesText}
              onChange={(e) => setOverlayValuesText(e.target.value)}
              multiline
              minRows={3}
              size="small"
              InputProps={{
                sx: {
                  background: 'rgba(255,255,255,0.03)',
                  borderRadius: '10px',
                  fontFamily: 'monospace',
                  fontSize: '0.75rem',
                  '& fieldset': { borderColor: 'rgba(255,255,255,0.08)' },
                  '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.14)' },
                  '&.Mui-focused fieldset': { borderColor: 'rgba(192,156,88,0.25)' },
                },
              }}
              InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.45)' } }}
              FormHelperTextProps={{ sx: { color: 'rgba(255,255,255,0.3)', fontSize: '0.6rem' } }}
              helperText="One `name = number` per line. Floats 0–1 typical."
            />
            <TextField
              label="Narrative suffix"
              placeholder="Acting as Aura the Engineer; lean toward technical precision."
              value={overlaySuffix}
              onChange={(e) => setOverlaySuffix(e.target.value)}
              multiline
              minRows={2}
              size="small"
              InputProps={{
                sx: {
                  background: 'rgba(255,255,255,0.03)',
                  borderRadius: '10px',
                  '& fieldset': { borderColor: 'rgba(255,255,255,0.08)' },
                  '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.14)' },
                  '&.Mui-focused fieldset': { borderColor: 'rgba(192,156,88,0.25)' },
                },
              }}
              InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.45)' } }}
            />
          </Stack>
        )}
      </DialogContent>

      <DialogActions sx={{
        px: 3,
        pb: 2,
        borderTop: '1px solid rgba(255,255,255,0.05)',
        background: 'rgba(255,255,255,0.01)',
      }}>
        <Button
          onClick={onClose}
          sx={{
            color: 'rgba(255,255,255,0.5)',
            textTransform: 'none',
            '&:hover': { color: 'rgba(255,255,255,0.75)' },
          }}
        >
          Close
        </Button>
        {tab === "new" && (
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={creating || !newName.trim()}
            startIcon={creating ? <CircularProgress size={14} /> : null}
            sx={{
              background: 'rgba(192,156,88,0.15)',
              border: '1px solid rgba(192,156,88,0.25)',
              color: '#c09c58',
              textTransform: 'none',
              fontWeight: 600,
              borderRadius: '10px',
              '&:hover': {
                background: 'rgba(192,156,88,0.25)',
                borderColor: 'rgba(192,156,88,0.4)',
              },
              '&.Mui-disabled': {
                background: 'rgba(255,255,255,0.04)',
                color: 'rgba(255,255,255,0.25)',
              },
            }}
          >
            {creating ? "Creating\u2026" : "Create & switch"}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
