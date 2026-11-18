"use client";

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box,
  Typography,
  Button,
  Card,
  CardContent,
  CardHeader,
  Chip,
  IconButton,
  Alert,
  Divider,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  CircularProgress,
  Tooltip,
  Paper,
} from '@mui/material';
import PowerSettingsNewIcon from '@mui/icons-material/PowerSettingsNew';
import StopIcon from '@mui/icons-material/Stop';
import RefreshIcon from '@mui/icons-material/Refresh';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import PsychologyIcon from '@mui/icons-material/Psychology';
import TagIcon from '@mui/icons-material/Tag';
import GroupsIcon from '@mui/icons-material/Groups';
import CircleIcon from '@mui/icons-material/Circle';
import { API_BASE_URL } from '@/config';

type BotStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

interface DiscordEvent {
  event_id: string;
  timestamp: string;
  direction: 'in' | 'out';
  channel_name: string;
  guild_name: string;
  author_name: string;
  content: string;
  processing_time_ms?: number;
  emotional_state?: {
    dominant: string;
    intensity: number;
    description: string;
  };
}

interface DiscordStatus {
  status: BotStatus;
  bot_user: string | null;
  bot_user_id: number | null;
  connected_guilds: Array<{ id: string; name: string; member_count: number }>;
  config: {
    enabled: boolean;
    command_prefix: string;
    allowed_channels: string[];
    max_message_length: number;
    stream_responses: boolean;
    active_mode: boolean;
    active_cooldown_seconds: number;
  };
}

const SOCKET_URL = API_BASE_URL.replace(/^http/, 'ws') + '/discord/stream';

export default function DiscordPanel() {
  const [status, setStatus] = useState<BotStatus>('disconnected');
  const [botInfo, setBotInfo] = useState<DiscordStatus | null>(null);
  const [events, setEvents] = useState<DiscordEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  // ------------------------------------------------------------------
  // Fetch initial status
  // ------------------------------------------------------------------
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/discord/status`);
      const data: DiscordStatus = await res.json();
      setStatus(data.status);
      setBotInfo(data);
      setError(null);
    } catch (err) {
      setError('Failed to fetch Discord status. Is the backend running?');
    }
  }, []);

  // ------------------------------------------------------------------
  // Fetch recent events (polling fallback)
  // ------------------------------------------------------------------
  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/discord/events?count=30`);
      const data = await res.json();
      if (data.events && data.events.length > 0) {
        setEvents((prev) => {
          const existingIds = new Set(prev.map((e) => e.event_id));
          const newEvents = data.events.filter(
            (e: DiscordEvent) => !existingIds.has(e.event_id)
          );
          return [...prev, ...newEvents].slice(-100);
        });
      }
    } catch {
      // Silently ignore polling errors
    }
  }, []);

  // ------------------------------------------------------------------
  // WebSocket connection
  // ------------------------------------------------------------------
  useEffect(() => {
    fetchStatus();
    fetchEvents();

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      try {
        ws = new WebSocket(SOCKET_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log('[DiscordPanel] WebSocket connected');
        };

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'status_change') {
              setStatus(msg.data.status as BotStatus);
            } else if (msg.type === 'discord_event') {
              setEvents((prev) => {
                const exists = prev.some(
                  (e) => e.event_id === msg.data.event_id
                );
                if (exists) return prev;
                return [...prev, msg.data].slice(-100);
              });
            }
          } catch {
            // Ignore parse errors
          }
        };

        ws.onclose = () => {
          console.log('[DiscordPanel] WebSocket disconnected');
          reconnectTimer = setTimeout(connect, 3000);
        };

        ws.onerror = () => {
          ws?.close();
        };
      } catch {
        reconnectTimer = setTimeout(connect, 3000);
      }
    };

    connect();

    // Poll as fallback every 5s
    const pollInterval = setInterval(() => {
      fetchStatus();
      fetchEvents();
    }, 5000);

    return () => {
      clearTimeout(reconnectTimer);
      clearInterval(pollInterval);
      ws?.close();
    };
  }, [fetchStatus, fetchEvents]);

  // ------------------------------------------------------------------
  // Auto-scroll events
  // ------------------------------------------------------------------
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  // ------------------------------------------------------------------
  // Connect / Disconnect
  // ------------------------------------------------------------------
  const handleConnect = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/discord/connect`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to connect');
      setStatus('connecting');
      // Status will update via WebSocket when connected
    } catch (err: any) {
      setError(err.message || 'Failed to connect Discord bot');
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/discord/disconnect`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to disconnect');
      setStatus('disconnected');
    } catch (err: any) {
      setError(err.message || 'Failed to disconnect Discord bot');
    } finally {
      setLoading(false);
    }
  };

  // ------------------------------------------------------------------
  // Status helpers
  // ------------------------------------------------------------------
  const statusColor: Record<BotStatus, 'success' | 'warning' | 'error' | 'default'> = {
    disconnected: 'default',
    connecting: 'warning',
    connected: 'success',
    error: 'error',
  };

  const statusLabel: Record<BotStatus, string> = {
    disconnected: 'Disconnected',
    connecting: 'Connecting...',
    connected: 'Connected',
    error: 'Error',
  };

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <Card
      sx={{
        bgcolor: 'background.paper',
        border: '1px solid',
        borderColor: 'divider',
      }}
    >
      <CardHeader
        title={
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <PsychologyIcon sx={{ color: '#5865F2' }} />
            <Typography variant="h6">Discord Bot</Typography>
            <Chip
              icon={
                <CircleIcon
                  sx={{
                    fontSize: 10,
                    color:
                      status === 'connected'
                        ? '#4caf50'
                        : status === 'connecting'
                          ? '#ff9800'
                          : status === 'error'
                            ? '#f44336'
                            : '#9e9e9e',
                  }}
                />
              }
              label={statusLabel[status]}
              size="small"
              color={statusColor[status]}
              variant="outlined"
            />
          </Box>
        }
        action={
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Refresh Status">
              <IconButton onClick={fetchStatus} size="small">
                <RefreshIcon />
              </IconButton>
            </Tooltip>
            {status === 'connected' || status === 'connecting' ? (
              <Button
                variant="outlined"
                color="error"
                size="small"
                startIcon={loading ? <CircularProgress size={16} /> : <StopIcon />}
                onClick={handleDisconnect}
                disabled={loading}
              >
                Disconnect
              </Button>
            ) : (
              <Button
                variant="contained"
                size="small"
                startIcon={loading ? <CircularProgress size={16} /> : <PowerSettingsNewIcon />}
                onClick={handleConnect}
                disabled={loading}
                sx={{
                  bgcolor: '#5865F2',
                  '&:hover': { bgcolor: '#4752C4' },
                }}
              >
                Connect
              </Button>
            )}
          </Box>
        }
      />
      <Divider />

      <CardContent sx={{ pt: 1 }}>
        {/* Error alert */}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Bot Info */}
        {botInfo && status === 'connected' && (
          <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
            <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <TagIcon fontSize="small" color="action" />
                <Typography variant="body2">
                  <strong>{botInfo.bot_user}</strong>
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <GroupsIcon fontSize="small" color="action" />
                <Typography variant="body2">
                  {botInfo.connected_guilds.length} guild
                  {botInfo.connected_guilds.length !== 1 ? 's' : ''}
                </Typography>
              </Box>
              {botInfo.connected_guilds.length > 0 && (
                <Typography variant="body2" color="text.secondary">
                  {botInfo.connected_guilds.map((g) => g.name).join(', ')}
                </Typography>
              )}
              {botInfo.config.active_mode && (
                <Chip
                  label={`Active Mode (${botInfo.config.active_cooldown_seconds}s cooldown)`}
                  size="small"
                  color="warning"
                  variant="outlined"
                  sx={{ fontSize: 11 }}
                />
              )}
            </Box>
          </Paper>
        )}

        {/* Setup hint when disconnected */}
        {status === 'disconnected' && !botInfo?.config?.enabled && (
          <Alert severity="info" sx={{ mb: 2 }}>
            <Typography variant="body2">
              <strong>Discord bot is not enabled.</strong> Set these in your{' '}
              <code>.env</code> file:
            </Typography>
            <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 2 }}>
              <li>
                <code>AURA_DISCORD_ENABLED=true</code>
              </li>
              <li>
                <code>AURA_DISCORD_BOT_TOKEN=your_token_here</code>
              </li>
            </Box>
            <Typography variant="caption" color="text.secondary">
              Create a bot at{' '}
              <a
                href="https://discord.com/developers/applications"
                target="_blank"
                rel="noopener noreferrer"
              >
                discord.com/developers
              </a>
              . Enable "Message Content Intent" under Privileged
              Gateway Intents.
            </Typography>
          </Alert>
        )}

        {/* Config display */}
        {botInfo?.config?.enabled && status === 'disconnected' && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Bot is configured but not connected. Click <strong>Connect</strong>{' '}
            to bring Aura online on Discord.
          </Alert>
        )}

        <Divider sx={{ my: 1.5 }} />

        {/* I/O Event Log */}
        <Typography variant="subtitle2" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <ArrowForwardIcon fontSize="small" color="action" />
          Input / Output Log
          {events.length > 0 && (
            <Chip label={events.length} size="small" variant="outlined" sx={{ ml: 1 }} />
          )}
        </Typography>

        {events.length === 0 ? (
          <Box
            sx={{
              py: 4,
              textAlign: 'center',
              color: 'text.secondary',
              border: '1px dashed',
              borderColor: 'divider',
              borderRadius: 1,
            }}
          >
            <Typography variant="body2">
              {status === 'connected'
                ? 'Waiting for messages... Mention the bot on Discord to see events here.'
                : 'Connect the bot and send messages on Discord to see the I/O log.'}
            </Typography>
          </Box>
        ) : (
          <List
            dense
            sx={{
              maxHeight: 360,
              overflow: 'auto',
              bgcolor: 'background.default',
              borderRadius: 1,
              border: '1px solid',
              borderColor: 'divider',
            }}
          >
            {events.map((event) => (
              <ListItem
                key={event.event_id}
                sx={{
                  borderBottom: '1px solid',
                  borderColor: 'divider',
                  '&:last-child': { borderBottom: 'none' },
                  flexDirection: 'column',
                  alignItems: 'stretch',
                  py: 1,
                }}
              >
                {/* Header row */}
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    mb: 0.5,
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 28 }}>
                    {event.direction === 'in' ? (
                      <ArrowForwardIcon
                        fontSize="small"
                        sx={{ color: '#5865F2' }}
                      />
                    ) : (
                      <ArrowBackIcon
                        fontSize="small"
                        sx={{ color: '#4caf50' }}
                      />
                    )}
                  </ListItemIcon>
                  <Chip
                    label={event.direction === 'in' ? 'FROM DISCORD' : 'AURA RESPONSE'}
                    size="small"
                    color={event.direction === 'in' ? 'primary' : 'success'}
                    variant="outlined"
                    sx={{ fontSize: 10, height: 20 }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    {event.author_name} · #{event.channel_name}
                  </Typography>
                  {event.processing_time_ms != null && event.processing_time_ms > 0 && (
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                      {(event.processing_time_ms / 1000).toFixed(1)}s
                    </Typography>
                  )}
                  {event.emotional_state?.dominant && (
                    <Chip
                      label={`${event.emotional_state.dominant} ${(event.emotional_state.intensity * 100).toFixed(0)}%`}
                      size="small"
                      sx={{ fontSize: 10, height: 20, ml: 'auto' }}
                    />
                  )}
                </Box>

                {/* Content */}
                <ListItemText
                  primary={
                    <Typography
                      variant="body2"
                      sx={{
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        fontFamily: event.direction === 'out' ? 'inherit' : 'monospace',
                        fontSize: event.direction === 'out' ? '0.875rem' : '0.8rem',
                      }}
                    >
                      {event.content}
                    </Typography>
                  }
                />

                {/* Timestamp */}
                <Typography
                  variant="caption"
                  color="text.disabled"
                  sx={{ mt: 0.25 }}
                >
                  {new Date(event.timestamp).toLocaleTimeString()}
                </Typography>
              </ListItem>
            ))}
            <div ref={eventsEndRef} />
          </List>
        )}

        {/* Clear events button */}
        {events.length > 0 && (
          <Box sx={{ mt: 1, textAlign: 'right' }}>
            <Button
              size="small"
              onClick={() => setEvents([])}
              color="inherit"
            >
              Clear Log
            </Button>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
