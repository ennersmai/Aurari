/**
 * SessionSwitcher — compact glass pill that shows the active session and opens the
 * full SessionsPanel for create / switch / pause / end.
 *
 * Lives at the top of the conversations sidebar. Per V1PRD §4 sessions are
 * the unit of *agent* scope, not *self* scope — Aura's emotion stays shared,
 * which is why we never show an "isolate emotion" toggle here.
 */

import React, { useState, useCallback } from "react";
import { Box, Button, Chip, Tooltip, Typography } from "@mui/material";
import LayersIcon from "@mui/icons-material/Layers";
import AddIcon from "@mui/icons-material/Add";
import type { Session } from "@/services/sessionService";
import sessionService from "@/services/sessionService";
import SessionsPanel from "./SessionsPanel";

interface SessionSwitcherProps {
  activeSession: Session | null;
  onActiveSessionChange: (session: Session | null) => void;
  onSessionsChanged?: () => void;
}

export default function SessionSwitcher({
  activeSession,
  onActiveSessionChange,
  onSessionsChanged,
}: SessionSwitcherProps) {
  const [panelOpen, setPanelOpen] = useState(false);

  const isMain = sessionService.isMain(activeSession?.session_id);
  const label = activeSession?.name ?? "Main";
  const modeLabel = activeSession?.mode ?? "main";
  const status = activeSession?.status ?? "active";

  const open = useCallback(() => setPanelOpen(true), []);
  const close = useCallback(() => setPanelOpen(false), []);

  return (
    <>
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          px: 2,
          py: 1.5,
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          background: 'rgba(18,18,22,0.3)',
          backdropFilter: 'blur(14px) saturate(160%)',
          WebkitBackdropFilter: 'blur(14px) saturate(160%)',
        }}
      >
        <Tooltip title="Switch or manage sessions">
          <Chip
            icon={<LayersIcon fontSize="small" />}
            label={
              <Box sx={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
                <Typography
                  variant="caption"
                  sx={{ fontSize: 9, opacity: 0.6, letterSpacing: 0.4 }}
                >
                  SESSION · {modeLabel.toUpperCase()}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {label}
                </Typography>
              </Box>
            }
            onClick={open}
            sx={{
              flex: 1,
              height: "auto",
              py: 0.75,
              cursor: "pointer",
              justifyContent: "flex-start",
              background: isMain
                ? 'rgba(255,255,255,0.04)'
                : 'rgba(192,156,88,0.1)',
              border: isMain
                ? '1px solid rgba(255,255,255,0.08)'
                : '1px solid rgba(192,156,88,0.2)',
              borderRadius: '12px',
              color: isMain ? 'rgba(255,255,255,0.75)' : '#c09c58',
              backdropFilter: 'blur(10px) saturate(150%)',
              WebkitBackdropFilter: 'blur(10px) saturate(150%)',
              "& .MuiChip-label": { display: "block", px: 1, py: 0.25 },
              "&:hover": {
                background: isMain
                  ? 'rgba(255,255,255,0.07)'
                  : 'rgba(192,156,88,0.16)',
                borderColor: isMain
                  ? 'rgba(255,255,255,0.14)'
                  : 'rgba(192,156,88,0.3)',
              },
              transition: 'all 0.2s ease',
            }}
          />
        </Tooltip>
        <Tooltip title="New session">
          <Button
            size="small"
            variant="outlined"
            onClick={open}
            sx={{
              minWidth: 36,
              px: 0.5,
              borderRadius: '10px',
              border: '1px solid rgba(255,255,255,0.08)',
              color: 'rgba(255,255,255,0.5)',
              background: 'rgba(255,255,255,0.02)',
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
              "&:hover": {
                borderColor: 'rgba(255,255,255,0.14)',
                background: 'rgba(255,255,255,0.06)',
                color: 'rgba(255,255,255,0.75)',
              },
              transition: 'all 0.2s ease',
            }}
          >
            <AddIcon fontSize="small" />
          </Button>
        </Tooltip>
      </Box>
      {status === "paused" && (
        <Box
          sx={{
            px: 2,
            py: 0.5,
            backgroundColor: "rgba(255,180,0,0.06)",
            borderBottom: "1px solid rgba(255,180,0,0.12)",
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
          }}
        >
          <Typography variant="caption" sx={{ color: "#f0b400", fontSize: '0.65rem' }}>
            ⏸ This session is paused — agents won't run until resumed.
          </Typography>
        </Box>
      )}

      <SessionsPanel
        open={panelOpen}
        onClose={close}
        activeSession={activeSession}
        onSelectSession={(session) => {
          onActiveSessionChange(session);
          close();
        }}
        onSessionsChanged={onSessionsChanged}
      />
    </>
  );
}
