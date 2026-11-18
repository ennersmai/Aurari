import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import Head from 'next/head';
import {
  Box,
  Typography,
  IconButton,
  Button,
  CircularProgress,
  Switch,
  Slider,
  TextField,
  Chip,
  Tooltip,
  Paper,
  Divider,
  useTheme,
  useMediaQuery,
  Tabs,
  Tab,
  List,
  ListItem,
  ListItemText,
  ListItemAvatar,
  Avatar,
  ListItemSecondaryAction,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControlLabel,
  FormGroup,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Stack,
  Card,
  CardContent,
  Grid,
  MenuItem,
  Select,
  InputLabel,
  FormControl,
  Badge,
  Alert,
  Snackbar,
  ToggleButtonGroup,
  ToggleButton,
  FormHelperText,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import RefreshIcon from '@mui/icons-material/Refresh';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import ChatIcon from '@mui/icons-material/Chat';
import HomeIcon from '@mui/icons-material/Home';
import SettingsIcon from '@mui/icons-material/Settings';
import AnalyticsIcon from '@mui/icons-material/Analytics';
import ChannelIcon from '@mui/icons-material/CallToAction';
import HistoryIcon from '@mui/icons-material/History';
import MuteIcon from '@mui/icons-material/VolumeOff';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import EmojiEmotionsIcon from '@mui/icons-material/EmojiEmotions';
import RuleIcon from '@mui/icons-material/Rule';
import SendIcon from '@mui/icons-material/Send';
import CloseIcon from '@mui/icons-material/Close';
import { API_BASE_URL } from '@/config';
import { ParticlesBackground } from '@/components/animation/ParticlesBackground';

// ── Types ───────────────────────────────────────────────────────────────────

interface GuildInfo {
  id: string;
  name: string;
  member_count?: number;
  channels?: Array<{ id: string; name: string }>;
}

interface DiscordConfig {
  enabled: boolean;
  command_prefix: string;
  allowed_channels: string[];
  max_message_length: number;
  stream_responses: boolean;
  active_mode: boolean;
  active_cooldown_seconds: number;
}

interface DiscordStatus {
  status: string;
  bot_user: string | null;
  bot_user_id: number | null;
  connected_guilds: GuildInfo[];
  config: DiscordConfig;
}

interface DiscordEvent {
  event_id: string;
  timestamp: string;
  direction: 'in' | 'out';
  channel_id: string;
  channel_name: string;
  guild_id: string;
  guild_name: string;
  author_id: string;
  author_name: string;
  content: string;
  processing_time_ms: number | null;
  emotional_state: string | object | null;
}

interface ChannelStats {
  channel_id: string;
  channel_name: string;
  guild_id: string;
  guild_name: string;
  total_messages: number;
  incoming_count: number;
  outgoing_count: number;
  avg_response_time_ms: number;
  last_activity: string | null;
  unique_users: number;
  is_muted: boolean;
  response_rules: Record<string, any>;
}

interface EventStats {
  total_events: number;
  incoming_count: number;
  outgoing_count: number;
  avg_response_time_ms: number;
  top_channels: Array<{ channel_id: string; count: number; name: string; guild: string }>;
  top_users: Array<{ user_id: string; count: number; name: string }>;
  events_per_hour: Array<{ hour: string; count: number }>;
}

interface ContextChannel {
  channel_id: string;
  channel_name: string;
  guild_name: string;
  messages: Array<{
    event_id: string;
    timestamp: string;
    direction: string;
    author_name: string;
    author_id: string;
    content: string;
    channel_name: string;
    guild_name: string;
  }>;
}

interface ContextData {
  total_messages: number;
  channels: ContextChannel[];
}

// ── Styles ──────────────────────────────────────────────────────────────────

const glassSx = {
  background: 'rgba(14,14,18,0.78)',
  backdropFilter: 'blur(20px) saturate(180%)',
  WebkitBackdropFilter: 'blur(20px) saturate(180%)',
  border: '1px solid rgba(255,255,255,0.06)',
  borderRadius: '14px',
};

const goldSx = { color: '#c09c58' };

// ── Helper Functions ────────────────────────────────────────────────────────

function formatTimestamp(ts: string): string {
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString();
  } catch {
    return 'Unknown';
  }
}

function getEmotionalStateLabel(state: string | object | null): string {
  if (!state) return '';
  if (typeof state === 'string') return state;
  if (typeof state === 'object' && state !== null) {
    return (state as any).dominant || 'unknown';
  }
  return String(state);
}

// ── Component ───────────────────────────────────────────────────────────────

export default function DiscordPage() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const router = useRouter();

  // State
  const [status, setStatus] = useState<DiscordStatus | null>(null);
  const [events, setEvents] = useState<DiscordEvent[]>([]);
  const [channelStats, setChannelStats] = useState<ChannelStats[]>([]);
  const [eventStats, setEventStats] = useState<EventStats | null>(null);
  const [contextData, setContextData] = useState<ContextData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState(0); // 0=Overview, 1=Context, 2=Channels, 3=Event Feed, 4=Settings

  // WebSocket ref for real-time events
  const wsRef = useRef<WebSocket | null>(null);

  // Mute dialog state
  const [muteDialog, setMuteDialog] = useState<{ open: boolean; channelId: string; channelName: string; muted: boolean }>({
    open: false,
    channelId: '',
    channelName: '',
    muted: false,
  });

  // Rules dialog state
  const [rulesDialog, setRulesDialog] = useState<{
    open: boolean;
    channelId: string;
    channelName: string;
    enabled: boolean;
    minConfidence: number;
    cooldown: number;
  }>({
    open: false,
    channelId: '',
    channelName: '',
    enabled: true,
    minConfidence: 0.5,
    cooldown: 30,
  });

  // Snackbar
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' as 'success' | 'error' });

  // Context filter
  const [contextChannelFilter, setContextChannelFilter] = useState<string>('all');
  const [contextLimit, setContextLimit] = useState(50);

  // Event filter
  const [eventFilter, setEventFilter] = useState<'all' | 'in' | 'out'>('all');

  // Settings state
  const [settingsConfig, setSettingsConfig] = useState<DiscordConfig | null>(null);

  // ── Fetch Functions ──────────────────────────────────────────────────────

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/discord/status`);
      if (!res.ok) {
        if (res.status === 503) {
          setStatus(null);
          setError('Discord bot is not initialized. Check AURA_DISCORD_BOT_TOKEN.');
          return;
        }
        throw new Error(`HTTP ${res.status}`);
      }
      const data: DiscordStatus = await res.json();
      setStatus(data);
      setSettingsConfig(data.config);
      setError(null);
    } catch (e) {
      console.error('Failed to fetch Discord status:', e);
      setError('Failed to connect to backend. Is Aura running?');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/discord/events?count=100`);
      if (!res.ok) return;
      const data = await res.json();
      setEvents(data.events || []);
    } catch (e) {
      console.error('Failed to fetch Discord events:', e);
    }
  }, []);

  const fetchChannelStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/discord/channels`);
      if (!res.ok) return;
      const data = await res.json();
      setChannelStats(data || []);
    } catch (e) {
      console.error('Failed to fetch channel stats:', e);
    }
  }, []);

  const fetchEventStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/discord/events/stats`);
      if (!res.ok) return;
      const data = await res.json();
      setEventStats(data);
    } catch (e) {
      console.error('Failed to fetch event stats:', e);
    }
  }, []);

  const fetchContext = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (contextChannelFilter !== 'all') {
        params.set('channel_id', contextChannelFilter);
      }
      params.set('limit', contextLimit.toString());
      const res = await fetch(`${API_BASE_URL}/discord/context?${params}`);
      if (!res.ok) return;
      const data = await res.json();
      setContextData(data);
    } catch (e) {
      console.error('Failed to fetch context:', e);
    }
  }, [contextChannelFilter, contextLimit]);

  // Initial fetch
  useEffect(() => {
    fetchStatus();
    fetchEvents();
    fetchChannelStats();
    fetchEventStats();
    fetchContext();

    const interval = setInterval(() => {
      fetchStatus();
      fetchEvents();
      fetchChannelStats();
      fetchEventStats();
      fetchContext();
    }, 15000);

    return () => clearInterval(interval);
  }, [fetchStatus, fetchEvents, fetchChannelStats, fetchEventStats, fetchContext]);

  // ── WebSocket for real-time events ───────────────────────────────────────

  useEffect(() => {
    const wsUrl = API_BASE_URL.replace(/^http/, 'ws') + '/discord/stream';
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      try {
        ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => console.log('[Discord WS] Connected');
        ws.onmessage = (msg) => {
          try {
            const parsed = JSON.parse(msg.data);
            if (parsed.type === 'discord_event') {
              setEvents(prev => {
                const next = [parsed.data, ...prev];
                return next.slice(0, 200);
              });
            } else if (parsed.type === 'status_change') {
              fetchStatus();
            }
          } catch {}
        };
        ws.onclose = () => {
          console.log('[Discord WS] Disconnected, reconnecting in 5s...');
          reconnectTimer = setTimeout(connect, 5000);
        };
        ws.onerror = () => ws?.close();
      } catch {
        reconnectTimer = setTimeout(connect, 5000);
      }
    };

    connect();
    return () => {
      ws?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [fetchStatus]);

  // ── Actions ─────────────────────────────────────────────────────────────

  const handleConnect = async () => {
    setIsConnecting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/discord/connect`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchStatus();
      setSnackbar({ open: true, message: 'Discord bot connected successfully', severity: 'success' });
    } catch (e) {
      console.error('Failed to connect Discord bot:', e);
      setSnackbar({ open: true, message: 'Failed to connect Discord bot', severity: 'error' });
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setIsDisconnecting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/discord/disconnect`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchStatus();
      setSnackbar({ open: true, message: 'Discord bot disconnected', severity: 'success' });
    } catch (e) {
      console.error('Failed to disconnect Discord bot:', e);
      setSnackbar({ open: true, message: 'Failed to disconnect Discord bot', severity: 'error' });
    } finally {
      setIsDisconnecting(false);
    }
  };

  const handleMuteChannel = async (muted: boolean) => {
    try {
      const res = await fetch(`${API_BASE_URL}/discord/channel/${muted ? 'unmute' : 'mute'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel_id: muteDialog.channelId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchChannelStats();
      setSnackbar({ open: true, message: `Channel ${muted ? 'unmuted' : 'muted'} successfully`, severity: 'success' });
    } catch (e) {
      console.error('Failed to toggle mute:', e);
      setSnackbar({ open: true, message: 'Failed to toggle mute', severity: 'error' });
    } finally {
      setMuteDialog({ open: false, channelId: '', channelName: '', muted: false });
    }
  };

  const handleUpdateRules = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/discord/channel/rules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_id: rulesDialog.channelId,
          enabled: rulesDialog.enabled,
          min_response_confidence: rulesDialog.minConfidence,
          cooldown_seconds: rulesDialog.cooldown,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchChannelStats();
      setSnackbar({ open: true, message: 'Channel rules updated', severity: 'success' });
    } catch (e) {
      console.error('Failed to update rules:', e);
      setSnackbar({ open: true, message: 'Failed to update rules', severity: 'error' });
    } finally {
      setRulesDialog(prev => ({ ...prev, open: false }));
    }
  };

  const isConnected = status?.status === 'connected';
  const botName = typeof status?.bot_user === 'string' ? status.bot_user : 'Aura Bot';

  // Filtered events
  const filteredEvents = events.filter(e => eventFilter === 'all' || e.direction === eventFilter);

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <ParticlesBackground disableMouseTracking>
      <Head>
        <title>Discord Mission Control — Aura</title>
        <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no" />
      </Head>

      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100%', position: 'relative', overflow: 'hidden' }}>
        {/* Top Bar */}
        <Box sx={{
          py: 1.5, px: 2,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          borderRadius: '0 0 14px 14px',
          background: 'rgba(14,14,18,0.78)',
          backdropFilter: 'blur(24px) saturate(180%)',
          WebkitBackdropFilter: 'blur(24px) saturate(180%)',
          boxShadow: '0 4px 24px rgba(0,0,0,0.25)',
          position: 'sticky', top: 0, zIndex: 1100,
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <IconButton onClick={() => router.push('/chat')} sx={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px' }}>
              <ArrowBackIcon />
            </IconButton>
            <IconButton onClick={() => router.push('/')} sx={{ ml: 0.5, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px' }}>
              <HomeIcon />
            </IconButton>
            <Typography variant="h6" sx={{ ml: 1, fontWeight: 500, background: 'linear-gradient(90deg, #7289da 0%, #5865f2 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Discord Mission Control
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Tooltip title="Refresh all data">
              <IconButton onClick={() => { fetchStatus(); fetchEvents(); fetchChannelStats(); fetchEventStats(); fetchContext(); }} size="small" sx={glassSx}>
                <RefreshIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            {isConnected ? (
              <Button
                variant="contained"
                color="error"
                startIcon={isDisconnecting ? <CircularProgress size={16} /> : <StopIcon />}
                onClick={handleDisconnect}
                disabled={isDisconnecting}
                size="small"
                sx={{ textTransform: 'none', borderRadius: '10px', fontWeight: 600 }}
              >
                Disconnect
              </Button>
            ) : (
              <Button
                variant="contained"
                sx={{ background: '#5865f2', '&:hover': { background: '#4752c4' }, textTransform: 'none', borderRadius: '10px', fontWeight: 600 }}
                startIcon={isConnecting ? <CircularProgress size={16} /> : <PlayArrowIcon />}
                onClick={handleConnect}
                disabled={isConnecting}
                size="small"
              >
                Connect
              </Button>
            )}
          </Box>
        </Box>

        {/* Main Content */}
        <Box sx={{ flexGrow: 1, overflow: 'auto', p: { xs: 2, md: 3 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {isLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flexGrow: 1 }}>
              <CircularProgress />
            </Box>
          ) : error && !status ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flexGrow: 1 }}>
              <Paper sx={{ ...glassSx, p: 4, maxWidth: 500, textAlign: 'center' }}>
                <Typography color="error" gutterBottom>{error}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Make sure AURA_DISCORD_BOT_TOKEN is set in your .env file.
                </Typography>
                <Button variant="outlined" onClick={fetchStatus}>Retry</Button>
              </Paper>
            </Box>
          ) : (
            <>
              {/* Status Overview Cards */}
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6} md={3}>
                  <Card sx={{ ...glassSx }}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="caption" color="text.secondary">BOT STATUS</Typography>
                        <Chip
                          label={isConnected ? 'ONLINE' : 'OFFLINE'}
                          size="small"
                          sx={{
                            fontWeight: 700, fontSize: '0.65rem',
                            background: isConnected ? 'rgba(87,242,135,0.15)' : 'rgba(255,100,100,0.15)',
                            color: isConnected ? '#57f287' : '#f47272',
                            border: `1px solid ${isConnected ? 'rgba(87,242,135,0.3)' : 'rgba(255,100,100,0.3)'}`,
                          }}
                        />
                      </Box>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>{botName}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Card sx={{ ...glassSx }}>
                    <CardContent>
                      <Typography variant="caption" color="text.secondary">GUILDS</Typography>
                      <Typography variant="h4" sx={{ fontWeight: 700, mt: 0.5 }}>{status?.connected_guilds?.length || 0}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Card sx={{ ...glassSx }}>
                    <CardContent>
                      <Typography variant="caption" color="text.secondary">TOTAL EVENTS</Typography>
                      <Typography variant="h4" sx={{ fontWeight: 700, mt: 0.5 }}>{eventStats?.total_events || events.length}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Card sx={{ ...glassSx }}>
                    <CardContent>
                      <Typography variant="caption" color="text.secondary">AVG RESPONSE</Typography>
                      <Typography variant="h4" sx={{ fontWeight: 700, mt: 0.5 }}>
                        {eventStats?.avg_response_time_ms ? `${eventStats.avg_response_time_ms.toFixed(0)}ms` : 'N/A'}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {/* Tab Navigation */}
              <Paper sx={{ ...glassSx, p: 0 }}>
                <Tabs
                  value={activeTab}
                  onChange={(_, newValue) => setActiveTab(newValue)}
                  variant="scrollable"
                  scrollButtons="auto"
                  sx={{
                    borderBottom: 1,
                    borderColor: 'rgba(255,255,255,0.06)',
                    '& .MuiTab-root': {
                      minWidth: 0,
                      fontSize: '0.75rem',
                      textTransform: 'none',
                      padding: '12px 16px',
                      color: 'rgba(255,255,255,0.5)',
                      fontWeight: 500,
                      '&.Mui-selected': { color: '#c09c58' },
                    },
                    '& .MuiTabs-indicator': {
                      backgroundColor: '#c09c58',
                    },
                  }}
                >
                  <Tab icon={<AnalyticsIcon />} label="Overview" />
                  <Tab icon={<ChatIcon />} label="Context" />
                  <Tab icon={<ChannelIcon />} label="Channels" />
                  <Tab icon={<HistoryIcon />} label="Event Feed" />
                  <Tab icon={<SettingsIcon />} label="Settings" />
                </Tabs>

                {/* Tab Panels */}
                <Box sx={{ p: { xs: 2, md: 3 } }}>
                  {/* Tab 0: Overview */}
                  {activeTab === 0 && (
                    <Box>
                      <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>Activity Overview</Typography>

                      {/* Incoming vs Outgoing */}
                      <Grid container spacing={2} sx={{ mb: 3 }}>
                        <Grid item xs={12} md={6}>
                          <Card sx={{ ...glassSx }}>
                            <CardContent>
                              <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>Message Flow</Typography>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                                <Box sx={{ textAlign: 'center' }}>
                                  <Typography variant="h4" sx={{ color: '#7289da', fontWeight: 700 }}>{eventStats?.incoming_count || 0}</Typography>
                                  <Typography variant="caption" color="text.secondary">Incoming</Typography>
                                </Box>
                                <Box sx={{ textAlign: 'center' }}>
                                  <Typography variant="h4" sx={{ color: '#57f287', fontWeight: 700 }}>{eventStats?.outgoing_count || 0}</Typography>
                                  <Typography variant="caption" color="text.secondary">Outgoing</Typography>
                                </Box>
                              </Box>
                            </CardContent>
                          </Card>
                        </Grid>
                        <Grid item xs={12} md={6}>
                          <Card sx={{ ...glassSx }}>
                            <CardContent>
                              <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>Top Channels</Typography>
                              <List dense>
                                {(eventStats?.top_channels?.slice(0, 5) || []).map((ch, idx) => (
                                  <ListItem key={ch.channel_id} sx={{ px: 0 }}>
                                    <ListItemText
                                      primary={`${ch.name || ch.channel_id}`}
                                      secondary={ch.guild || ''}
                                      primaryTypographyProps={{ fontSize: '0.85rem', fontWeight: 500 }}
                                      secondaryTypographyProps={{ fontSize: '0.75rem' }}
                                    />
                                    <ListItemSecondaryAction>
                                      <Chip label={`${ch.count}`} size="small" sx={{ fontWeight: 700 }} />
                                    </ListItemSecondaryAction>
                                  </ListItem>
                                ))}
                              </List>
                            </CardContent>
                          </Card>
                        </Grid>
                      </Grid>

                      {/* Recent Activity */}
                      <Card sx={{ ...glassSx }}>
                        <CardContent>
                          <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>Recent Activity</Typography>
                          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                            {events.slice(0, 10).map((event) => (
                              <Box key={event.event_id} sx={{
                                p: 1.5,
                                borderRadius: '10px',
                                background: event.direction === 'in' ? 'rgba(88,101,242,0.06)' : 'rgba(87,242,135,0.04)',
                                border: '1px solid',
                                borderColor: event.direction === 'in' ? 'rgba(88,101,242,0.12)' : 'rgba(87,242,135,0.08)',
                              }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                    <Chip
                                      label={event.direction === 'in' ? 'IN' : 'OUT'}
                                      size="small"
                                      sx={{
                                        height: 18, fontSize: '0.6rem', fontWeight: 700,
                                        background: event.direction === 'in' ? 'rgba(88,101,242,0.2)' : 'rgba(87,242,135,0.15)',
                                        color: event.direction === 'in' ? '#7289da' : '#57f287',
                                      }}
                                    />
                                    <Typography variant="caption" sx={{ fontWeight: 600 }}>{event.author_name}</Typography>
                                    <Typography variant="caption" color="text.secondary">#{event.channel_name}</Typography>
                                  </Box>
                                  <Typography variant="caption" color="text.secondary">{formatTimestamp(event.timestamp)}</Typography>
                                </Box>
                                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '0.8rem', opacity: 0.8 }}>
                                  {typeof event.content === 'string' ? event.content : JSON.stringify(event.content)}
                                </Typography>
                              </Box>
                            ))}
                          </Box>
                        </CardContent>
                      </Card>
                    </Box>
                  )}

                  {/* Tab 1: Context */}
                  {activeTab === 1 && (
                    <Box>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2, flexWrap: 'wrap', gap: 2 }}>
                        <Typography variant="h6" sx={{ fontWeight: 600 }}>Conversation Context</Typography>
                        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                          <FormControl size="small" sx={{ minWidth: 150 }}>
                            <InputLabel>Channel</InputLabel>
                            <Select
                              value={contextChannelFilter}
                              label="Channel"
                              onChange={(e) => setContextChannelFilter(e.target.value)}
                            >
                              <MenuItem value="all">All Channels</MenuItem>
                              {channelStats.map((ch) => (
                                <MenuItem key={ch.channel_id} value={ch.channel_id}>{ch.channel_name}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                          <FormControl size="small" sx={{ minWidth: 100 }}>
                            <InputLabel>Limit</InputLabel>
                            <Select
                              value={contextLimit}
                              label="Limit"
                              onChange={(e) => setContextLimit(Number(e.target.value))}
                            >
                              <MenuItem value={25}>25</MenuItem>
                              <MenuItem value={50}>50</MenuItem>
                              <MenuItem value={100}>100</MenuItem>
                            </Select>
                          </FormControl>
                          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={fetchContext}>
                            Refresh
                          </Button>
                        </Box>
                      </Box>

                      {contextData?.channels.map((channel) => (
                        <Card key={channel.channel_id} sx={{ ...glassSx, mb: 2 }}>
                          <CardContent>
                            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                              <Box>
                                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{channel.channel_name}</Typography>
                                <Typography variant="caption" color="text.secondary">{channel.guild_name} • {channel.messages.length} messages</Typography>
                              </Box>
                            </Box>
                            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                              {channel.messages.map((msg) => (
                                <Box key={msg.event_id} sx={{
                                  p: 1.5,
                                  borderRadius: '10px',
                                  background: msg.direction === 'in' ? 'rgba(88,101,242,0.06)' : 'rgba(87,242,135,0.04)',
                                  border: '1px solid',
                                  borderColor: msg.direction === 'in' ? 'rgba(88,101,242,0.12)' : 'rgba(87,242,135,0.08)',
                                }}>
                                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                      <Chip
                                        label={msg.direction === 'in' ? 'IN' : 'OUT'}
                                        size="small"
                                        sx={{
                                          height: 16, fontSize: '0.55rem', fontWeight: 700,
                                          background: msg.direction === 'in' ? 'rgba(88,101,242,0.2)' : 'rgba(87,242,135,0.15)',
                                          color: msg.direction === 'in' ? '#7289da' : '#57f287',
                                        }}
                                      />
                                      <Typography variant="caption" sx={{ fontWeight: 600 }}>{msg.author_name}</Typography>
                                    </Box>
                                    <Typography variant="caption" color="text.secondary">{formatTimestamp(msg.timestamp)}</Typography>
                                  </Box>
                                  <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '0.8rem', opacity: 0.8 }}>
                                    {msg.content}
                                  </Typography>
                                </Box>
                              ))}
                            </Box>
                          </CardContent>
                        </Card>
                      ))}

                      {!contextData || contextData.channels.length === 0 ? (
                        <Box sx={{ textAlign: 'center', py: 6 }}>
                          <ChatIcon sx={{ fontSize: 48, color: 'rgba(255,255,255,0.1)', mb: 2 }} />
                          <Typography color="text.secondary" variant="body2">No context data available. Connect the bot and interact on Discord!</Typography>
                        </Box>
                      ) : null}
                    </Box>
                  )}

                  {/* Tab 2: Channels */}
                  {activeTab === 2 && (
                    <Box>
                      <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>Channel Management</Typography>

                      <Card sx={{ ...glassSx }}>
                        <CardContent>
                          <List>
                            {channelStats.map((ch) => (
                              <ListItem
                                key={ch.channel_id}
                                sx={{
                                  px: 0,
                                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                                  flexDirection: { xs: 'column', sm: 'row' },
                                  gap: { xs: 1, sm: 0 },
                                }}
                              >
                                <Box sx={{ flex: 1, minWidth: 0 }}>
                                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{ch.channel_name}</Typography>
                                    <Typography variant="caption" color="text.secondary">#{ch.guild_name}</Typography>
                                    {ch.is_muted && (
                                      <Chip label="MUTED" size="small" sx={{ height: 18, fontSize: '0.6rem', background: 'rgba(255,100,100,0.15)', color: '#f47272' }} />
                                    )}
                                  </Box>
                                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                                    <Typography variant="caption" color="text.secondary">
                                      {ch.incoming_count} in / {ch.outgoing_count} out
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                      Avg: {ch.avg_response_time_ms.toFixed(0)}ms
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                      {ch.unique_users} users
                                    </Typography>
                                  </Box>
                                </Box>
                                <Box sx={{ display: 'flex', gap: 1, mt: { xs: 1, sm: 0 } }}>
                                  <Tooltip title={ch.is_muted ? 'Unmute channel' : 'Mute channel'}>
                                    <IconButton
                                      size="small"
                                      onClick={() => setMuteDialog({ open: true, channelId: ch.channel_id, channelName: ch.channel_name, muted: ch.is_muted })}
                                      sx={{ color: ch.is_muted ? '#f47272' : '#57f287' }}
                                    >
                                      {ch.is_muted ? <MuteIcon fontSize="small" /> : <VolumeUpIcon fontSize="small" />}
                                    </IconButton>
                                  </Tooltip>
                                  <Tooltip title="Response Rules">
                                    <IconButton
                                      size="small"
                                      onClick={() => setRulesDialog({
                                        open: true,
                                        channelId: ch.channel_id,
                                        channelName: ch.channel_name,
                                        enabled: ch.response_rules?.enabled ?? true,
                                        minConfidence: ch.response_rules?.min_response_confidence ?? 0.5,
                                        cooldown: ch.response_rules?.cooldown_seconds ?? 30,
                                      })}
                                    >
                                      <RuleIcon fontSize="small" />
                                    </IconButton>
                                  </Tooltip>
                                </Box>
                              </ListItem>
                            ))}
                          </List>
                          {channelStats.length === 0 && (
                            <Box sx={{ textAlign: 'center', py: 4 }}>
                              <ChannelIcon sx={{ fontSize: 48, color: 'rgba(255,255,255,0.1)', mb: 2 }} />
                              <Typography color="text.secondary" variant="body2">No channels found. Connect to Discord to see channel stats.</Typography>
                            </Box>
                          )}
                        </CardContent>
                      </Card>
                    </Box>
                  )}

                  {/* Tab 3: Event Feed */}
                  {activeTab === 3 && (
                    <Box>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2, flexWrap: 'wrap', gap: 2 }}>
                        <Typography variant="h6" sx={{ fontWeight: 600 }}>Live Event Feed</Typography>
                        <ToggleButtonGroup size="small" value={eventFilter} exclusive onChange={(_, val) => {
                          if (val === 'all' || val === 'in' || val === 'out') setEventFilter(val);
                        }} aria-label="event filter">
                          <ToggleButton value="all" sx={{ textTransform: 'none', fontSize: '0.7rem' }}>All</ToggleButton>
                          <ToggleButton value="in" sx={{ textTransform: 'none', fontSize: '0.7rem', color: eventFilter === 'in' ? '#7289da' : undefined }}>Incoming</ToggleButton>
                          <ToggleButton value="out" sx={{ textTransform: 'none', fontSize: '0.7rem', color: eventFilter === 'out' ? '#57f287' : undefined }}>Outgoing</ToggleButton>
                        </ToggleButtonGroup>
                      </Box>

                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        {filteredEvents.map((event) => (
                          <Box key={event.event_id} sx={{
                            p: 1.5,
                            borderRadius: '10px',
                            background: event.direction === 'in' ? 'rgba(88,101,242,0.06)' : 'rgba(87,242,135,0.04)',
                            border: '1px solid',
                            borderColor: event.direction === 'in' ? 'rgba(88,101,242,0.12)' : 'rgba(87,242,135,0.08)',
                          }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                                <Chip
                                  label={event.direction === 'in' ? 'IN' : 'OUT'}
                                  size="small"
                                  sx={{
                                    height: 18, fontSize: '0.6rem', fontWeight: 700,
                                    background: event.direction === 'in' ? 'rgba(88,101,242,0.2)' : 'rgba(87,242,135,0.15)',
                                    color: event.direction === 'in' ? '#7289da' : '#57f287',
                                  }}
                                />
                                <Typography variant="caption" sx={{ fontWeight: 600 }}>{event.author_name}</Typography>
                                <Typography variant="caption" color="text.secondary">#{event.channel_name}</Typography>
                                <Typography variant="caption" color="text.secondary">{event.guild_name}</Typography>
                                {event.processing_time_ms && (
                                  <Typography variant="caption" color="text.secondary">
                                    ({event.processing_time_ms}ms)
                                  </Typography>
                                )}
                              </Box>
                              <Typography variant="caption" color="text.secondary">{formatTimestamp(event.timestamp)}</Typography>
                            </Box>
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '0.8rem', opacity: 0.8 }}>
                              {typeof event.content === 'string' ? event.content : JSON.stringify(event.content)}
                            </Typography>
                            {event.emotional_state && (
                              <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: '#c09c58' }}>
                                Emotion: {getEmotionalStateLabel(event.emotional_state)}
                              </Typography>
                            )}
                          </Box>
                        ))}
                      </Box>

                      {filteredEvents.length === 0 && (
                        <Box sx={{ textAlign: 'center', py: 6 }}>
                          <HistoryIcon sx={{ fontSize: 48, color: 'rgba(255,255,255,0.1)', mb: 2 }} />
                          <Typography color="text.secondary" variant="body2">No events found. {eventFilter !== 'all' ? `Filtering by: ${eventFilter}` : ''}</Typography>
                        </Box>
                      )}
                    </Box>
                  )}

                  {/* Tab 4: Settings */}
                  {activeTab === 4 && (
                    <Box>
                      <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>Discord Settings</Typography>

                      {settingsConfig ? (
                        <Card sx={{ ...glassSx }}>
                          <CardContent>
                            <Grid container spacing={3}>
                              <Grid item xs={12} md={6}>
                                <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>General</Typography>
                                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                                  <Box>
                                    <Typography variant="caption" color="text.secondary" display="block">Command Prefix</Typography>
                                    <Typography variant="body2">{settingsConfig.command_prefix}</Typography>
                                  </Box>
                                  <Box>
                                    <Typography variant="caption" color="text.secondary" display="block">Max Message Length</Typography>
                                    <Typography variant="body2">{settingsConfig.max_message_length} characters</Typography>
                                  </Box>
                                  <FormControlLabel
                                    control={<Switch checked={settingsConfig.stream_responses} disabled />}
                                    label="Stream Responses"
                                    sx={{ mt: 1 }}
                                  />
                                  <FormControlLabel
                                    control={<Switch checked={settingsConfig.active_mode} disabled />}
                                    label="Active Mode"
                                    sx={{ mt: 1 }}
                                  />
                                </Box>
                              </Grid>
                              <Grid item xs={12} md={6}>
                                <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>Active Mode</Typography>
                                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                                  <Box>
                                    <Typography variant="caption" color="text.secondary" display="block">Cooldown</Typography>
                                    <Typography variant="body2">{settingsConfig.active_cooldown_seconds} seconds</Typography>
                                  </Box>
                                  <Box>
                                    <Typography variant="caption" color="text.secondary" display="block">Allowed Channels</Typography>
                                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                                      {settingsConfig.allowed_channels.map((ch) => (
                                        <Chip key={ch} label={ch} size="small" sx={{ fontSize: '0.65rem' }} />
                                      ))}
                                    </Box>
                                  </Box>
                                </Box>
                              </Grid>
                            </Grid>
                            <Box sx={{ mt: 3, p: 2, borderRadius: 2, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
                              <Typography variant="caption" color="text.secondary">
                                Note: Advanced settings are managed via environment variables. Contact administrator to modify.
                              </Typography>
                            </Box>
                          </CardContent>
                        </Card>
                      ) : (
                        <Box sx={{ textAlign: 'center', py: 6 }}>
                          <SettingsIcon sx={{ fontSize: 48, color: 'rgba(255,255,255,0.1)', mb: 2 }} />
                          <Typography color="text.secondary" variant="body2">No settings available. Connect to Discord to see settings.</Typography>
                        </Box>
                      )}
                    </Box>
                  )}
                </Box>
              </Paper>
            </>
          )}
        </Box>

        {/* Mute Dialog */}
        <Dialog open={muteDialog.open} onClose={() => setMuteDialog(prev => ({ ...prev, open: false }))} maxWidth="xs" fullWidth>
          <DialogTitle>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {muteDialog.muted ? <VolumeUpIcon /> : <MuteIcon />}
              {muteDialog.muted ? 'Unmute Channel' : 'Mute Channel'}
            </Box>
          </DialogTitle>
          <DialogContent>
            <Typography variant="body2" sx={{ mt: 1 }}>
              Are you sure you want to {muteDialog.muted ? 'unmute' : 'mute'} <strong>{muteDialog.channelName}</strong>?
              {muteDialog.muted ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Aura will start responding to messages in this channel again.
                </Typography>
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Aura will stop responding to messages in this channel.
                </Typography>
              )}
            </Typography>
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setMuteDialog(prev => ({ ...prev, open: false }))}>Cancel</Button>
            <Button
              onClick={() => handleMuteChannel(muteDialog.muted)}
              color={muteDialog.muted ? 'success' : 'warning'}
              variant="contained"
            >
              {muteDialog.muted ? 'Unmute' : 'Mute'}
            </Button>
          </DialogActions>
        </Dialog>

        {/* Rules Dialog */}
        <Dialog open={rulesDialog.open} onClose={() => setRulesDialog(prev => ({ ...prev, open: false }))} maxWidth="sm" fullWidth>
          <DialogTitle>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <RuleIcon />
              Response Rules — {rulesDialog.channelName}
            </Box>
          </DialogTitle>
          <DialogContent>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3, mt: 1 }}>
              <FormControlLabel
                control={
                  <Switch
                    checked={rulesDialog.enabled}
                    onChange={(e) => setRulesDialog(prev => ({ ...prev, enabled: e.target.checked }))}
                  />
                }
                label="Enable Response Rules"
              />

              <Box>
                <Typography variant="body2" sx={{ mb: 0.5 }}>Minimum Response Confidence</Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  <Slider
                    value={rulesDialog.minConfidence}
                    onChange={(_, val) => setRulesDialog(prev => ({ ...prev, minConfidence: val as number }))}
                    min={0}
                    max={1}
                    step={0.05}
                    marks
                    valueLabelDisplay="auto"
                    sx={{ flex: 1 }}
                  />
                </Box>
                <FormHelperText>Aura will only respond if confidence is above this threshold.</FormHelperText>
              </Box>

              <Box>
                <Typography variant="body2" sx={{ mb: 0.5 }}>Cooldown (seconds)</Typography>
                <TextField
                  type="number"
                  value={rulesDialog.cooldown}
                  onChange={(e) => setRulesDialog(prev => ({ ...prev, cooldown: Number(e.target.value) }))}
                  size="small"
                  sx={{ width: 150 }}
                  inputProps={{ min: 0, max: 300 }}
                />
                <FormHelperText>Minimum seconds between responses in this channel.</FormHelperText>
              </Box>
            </Box>
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setRulesDialog(prev => ({ ...prev, open: false }))}>Cancel</Button>
            <Button onClick={handleUpdateRules} variant="contained" color="primary">Save Rules</Button>
          </DialogActions>
        </Dialog>

        {/* Snackbar */}
        <Snackbar
          open={snackbar.open}
          autoHideDuration={4000}
          onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert
            onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
            severity={snackbar.severity}
            variant="filled"
            sx={{ minWidth: 300 }}
          >
            {snackbar.message}
          </Alert>
        </Snackbar>
      </Box>
    </ParticlesBackground>
  );
}
