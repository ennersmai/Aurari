import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  List,
  Divider,
  IconButton,
  Drawer,
  useMediaQuery,
  useTheme,
  CircularProgress,
  Fab,
  Button,
  ListItemButton,
  ListItemText,
  ListItemIcon,
  Container,
  Menu,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  TextField,
  Tabs,
  Tab,
  Tooltip
} from '@mui/material';
import ChatInput from '@/components/chat/ChatInput';
import ChatMessage from '@/components/chat/ChatMessage';
import { TierChip } from '@/components/chat/TurnMarkers';
import { useActiveTier } from '@/hooks/useActiveTier';
import NeuralSidebar from '@/components/neural/NeuralSidebar';
import { useSocket } from '@/hooks/useSocket';
import { useAppDispatch, useAppSelector } from '@/hooks/useRedux';
import { 
  fetchConversations as fetchConversationsAction, 
  setActiveConversation, 
  addMessage, 
  startStreamingResponse, 
  endStreamingResponse, 
  clearMessages, 
  fetchMessages,
  appendStreamToken 
} from '@/store/slices/chatSlice';
import MenuIcon from '@mui/icons-material/Menu';
import AddIcon from '@mui/icons-material/Add';
import CloseIcon from '@mui/icons-material/Close';
import HomeIcon from '@mui/icons-material/Home';
import DeleteIcon from '@mui/icons-material/Delete';
import DebugPanel from '@/components/debug/DebugPanel';
import socketService, { StreamTokenData } from '@/services/socketService';
import { useRouter } from 'next/router';
import Head from 'next/head';
import { apiService, Conversation } from '@/services/apiService';
import { auraApi } from '@/services/auraApiService';
import { API_BASE_URL } from '@/config';
import ChatIcon from '@mui/icons-material/Chat';
import BugReportIcon from '@mui/icons-material/BugReport';
import ServerStatusAlert from '@/components/common/ServerStatusAlert';
import { useServerStatus } from '@/contexts/ServerStatusContext';
import { useSettings } from '@/contexts/SettingsContext';
import RefreshIcon from '@mui/icons-material/Refresh';
import { ParticlesBackground } from '@/components/animation/ParticlesBackground';
import EditIcon from '@mui/icons-material/Edit';
import StreamingVisualizer from '../components/debug/StreamingVisualizer';
import TerminalIcon from '@mui/icons-material/Terminal';
import SchoolIcon from '@mui/icons-material/School';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import VolumeOffIcon from '@mui/icons-material/VolumeOff';
import SettingsVoiceIcon from '@mui/icons-material/SettingsVoice';
import BedtimeIcon from '@mui/icons-material/Bedtime';
import WbSunnyIcon from '@mui/icons-material/WbSunny';
import TimelineIcon from '@mui/icons-material/Timeline';
import HubIcon from '@mui/icons-material/Hub';
import DiscordIcon from '@mui/icons-material/Forum';
import CognitiveTelemetry from '@/components/telemetry/CognitiveTelemetry';
import GoalPursuitModal from '@/components/goal/GoalPursuitModal';
import SystemRestartModal from '@/components/system/SystemRestartModal';
import SystemDebugPanel from '@/components/debug/SystemDebugPanel';
import SessionSwitcher from '@/components/sessions/SessionSwitcher';
import sessionService, { type Session } from '@/services/sessionService';
import type { Goal, Memory, EmotionState } from '@/types/aura';
import SpiralAvatar from '@/components/SpiralAvatar';
import AvatarStage from '@/avatar/AvatarStage';
import ChartDialog from '@/components/chat/ChartRenderer';
import type { ChartJsConfig } from '@/components/chat/ChartRenderer';
import MemoryGraphDialog from '@/components/neural/MemoryGraphDialog';

// Socket.IO backend URL no longer needed - using direct Aura API calls
// const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

// Left sidebar content component with tabs
const ConversationsList = React.memo(function ConversationsList({ 
  onNewChat,
  emotion,
  memories,
  onRefreshMemories,
  activeSession,
  onActiveSessionChange,
  onSessionsChanged,
}: { 
  onNewChat: () => void;
  emotion: EmotionState;
  memories: Memory[];
  onRefreshMemories?: () => void;
  activeSession: Session | null;
  onActiveSessionChange: (session: Session | null) => void;
  onSessionsChanged?: () => void;
}) {
  const conversations = useAppSelector(state => state.chat.conversations);
  const activeConversationId = useAppSelector(state => state.chat.activeConversationId);
  const router = useRouter();
  const dispatch = useAppDispatch();
  const [isLoading, setIsLoading] = useState(false);
  const [leftDrawerTab, setLeftDrawerTab] = useState(0); // 0=Conversations, 1=Observatory, 2=System
  
  // Extract conversation ID from router (must be before refs that use it)
  const routeConversationId = router.query.id as string;
  
  // Get user settings for commander identity (must be before refs that use it)
  const { settings } = useSettings();
  const commanderIdentity = settings.commanderIdentity || "Mai";
  
  // TODO: Track last played animation for L3 awareness
  // Blocked by TypeScript scoping issue - needs investigation
  // Backend L5 already supports previous_animation field
  
  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    mouseX: number;
    mouseY: number;
    conversationId: string;
  } | null>(null);
  
  // Delete confirmation dialog state
  const [deleteDialog, setDeleteDialog] = useState<{
    open: boolean;
    conversationId: string;
    title: string;
  } | null>(null);
  
  // Rename dialog state
  const [renameDialog, setRenameDialog] = useState<{
    open: boolean;
    conversationId: string;
    title: string;
  } | null>(null);
  
  // For rename input
  const [newTitle, setNewTitle] = useState('');
  
  // FIX #1: Refs to avoid stale closures in context menu handlers
  // Declared after routeConversationId and commanderIdentity to avoid forward reference errors
  const conversationsRef = useRef(conversations);
  const activeConversationIdRef = useRef(activeConversationId);
  const routeConversationIdRef = useRef(routeConversationId);
  const commanderIdentityRef = useRef(commanderIdentity);
  
  // Keep refs in sync
  useEffect(() => { conversationsRef.current = conversations; }, [conversations]);
  useEffect(() => { activeConversationIdRef.current = activeConversationId; }, [activeConversationId]);
  useEffect(() => { routeConversationIdRef.current = routeConversationId; }, [routeConversationId]);
  useEffect(() => { commanderIdentityRef.current = commanderIdentity; }, [commanderIdentity]);
  
  // Track if window is visible to avoid polling when tab is hidden
  // Initial fetch on mount only - prevents cursor unfocus from constant refetching
  // FIX #2: Removed activeSession?.session_id from deps to prevent double-fetch race
  // with parent's onSessionsChanged callback. Session changes already trigger
  // conversation refresh via the parent's callback (line 1919-1921).
  useEffect(() => {
    const fetchConversations = async () => {
      try {
        setIsLoading(true);
        
        // Fetch via Redux (single source of truth)
        await dispatch(fetchConversationsAction(commanderIdentity));
        
        // FIX #2: Only sync URL→Redux on initial mount or when routeConversationId
        // changes independently (not when session changes, which is handled separately).
        const currentRouteId = routeConversationIdRef.current;
        const currentActiveId = activeConversationIdRef.current;
        if (currentRouteId && !currentActiveId) {
          dispatch(setActiveConversation(currentRouteId));
          dispatch(fetchMessages(currentRouteId));
        }
        
        setIsLoading(false);
      } catch (error) {
        console.error("Failed to fetch conversations:", error);
        setIsLoading(false);
      }
    };
    
    fetchConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatch, commanderIdentity]); // FIX #2: Removed activeSession?.session_id
  
  // Smart polling - disabled to prevent cursor unfocus issues
  // Conversations will refresh on manual actions (create/delete/rename) only
  // useEffect(() => {
  //   if (!isWindowVisible) {
  //     return;
  //   }
  //   
  //   const intervalId = setInterval(() => {
  //     if (!document.hidden) {
  //       dispatch(fetchConversationsAction(commanderIdentity));
  //     }
  //   }, 120000); // 2 minutes
  //   
  //   return () => clearInterval(intervalId);
  // }, [dispatch, commanderIdentity, isWindowVisible]);
  
  // Sort Redux conversations by most recent
  const allConversations = useMemo(() => {
    if (!Array.isArray(conversations)) return [];
    return [...conversations].sort((a, b) => {
      const aTime = a.updated_at ? new Date(a.updated_at).getTime() : new Date(a.created_at).getTime();
      const bTime = b.updated_at ? new Date(b.updated_at).getTime() : new Date(b.created_at).getTime();
      return bTime - aTime;
    });
  }, [conversations]);
  
  // Right-click context menu handlers
  const handleContextMenu = (event: React.MouseEvent, conversationId: string) => {
    event.preventDefault();
    setContextMenu({
      mouseX: event.clientX,
      mouseY: event.clientY,
      conversationId
    });
  };
  
  const handleCloseContextMenu = () => {
    setContextMenu(null);
  };
  
  const handleDeleteOption = () => {
    if (contextMenu) {
      // FIX #1: Use ref to get current conversations instead of stale closure
      const currentConversations = conversationsRef.current;
      const conversation = currentConversations.find(conv => conv.id === contextMenu.conversationId);
      const title = conversation?.title || "Untitled Conversation";
      
      // Open the confirmation dialog
      setDeleteDialog({
        open: true,
        conversationId: contextMenu.conversationId,
        title
      });
      
      // Close the context menu
      handleCloseContextMenu();
    }
  };
  
  const handleRenameOption = () => {
    if (contextMenu) {
      // FIX #1: Use ref to get current conversations instead of stale closure
      const currentConversations = conversationsRef.current;
      const conversation = currentConversations.find(conv => conv.id === contextMenu.conversationId);
      const title = conversation?.title || "Untitled Conversation";
      
      // Set the initial value for the rename input
      setNewTitle(title);
      
      // Open the rename dialog
      setRenameDialog({
        open: true,
        conversationId: contextMenu.conversationId,
        title
      });
      
      // Close the context menu
      handleCloseContextMenu();
    }
  };
  
  // FIX #5: Track mounted state to prevent dispatch after unmount
  const isMountedRef = useRef(true);
  
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);
  
  const handleConfirmDelete = async () => {
    if (deleteDialog) {
      try {
        // Delete the conversation using the API
        await apiService.deleteConversation(deleteDialog.conversationId);
        
        // FIX #5: Only dispatch if component is still mounted
        if (!isMountedRef.current) return;
        
        // If the deleted conversation is the active one, navigate to a new conversation
        const currentActiveId = activeConversationIdRef.current;
        if (deleteDialog.conversationId === currentActiveId) {
          dispatch(clearMessages());
          router.push('/chat', undefined, { shallow: true });
        }
        
        // FIX #5: Only refresh conversations if still mounted (skip if navigated away)
        if (router.pathname === '/chat') {
          dispatch(fetchConversationsAction(commanderIdentityRef.current));
        }
        
        console.log(`Conversation deleted: ${deleteDialog.conversationId}`);
      } catch (error) {
        console.error("Failed to delete conversation:", error);
      }
      
      // Close the dialog
      setDeleteDialog(null);
    }
  };
  
  const handleConfirmRename = async () => {
    if (renameDialog && newTitle.trim()) {
      try {
        // Update the conversation title using the API
        await apiService.updateConversation(renameDialog.conversationId, { title: newTitle.trim() });
        
        // Refresh the conversations list
        dispatch(fetchConversationsAction(commanderIdentity));
        
        console.log(`Conversation renamed: ${renameDialog.conversationId} to "${newTitle}"`);
      } catch (error) {
        console.error("Failed to rename conversation:", error);
      }
      
      // Close the dialog
      setRenameDialog(null);
    }
  };
  
  const handleCancelDelete = () => {
    setDeleteDialog(null);
  };
  
  const handleCancelRename = () => {
    setRenameDialog(null);
  };
  
  const handleSelectConversation = (id: string) => {
    if (!id) {
      console.error("Cannot select conversation: ID is empty");
      return;
    }
    
    console.log(`Selecting conversation: ${id}`);
    
    try {
      // Set active conversation immediately so UI highlights update
      dispatch(setActiveConversation(id));

      // FIX: dispatch fetchMessages directly here.
      // The URL-driven effect (routeConversationId !== activeConversationId) fires AFTER
      // setActiveConversation already made them equal, so it silently skips the fetch.
      // Dispatching here is the only reliable trigger point.
      dispatch(fetchMessages(id));

      // Update URL for deep-linking / back-navigation
      router.push(`/chat?id=${id}`, undefined, { shallow: true });
    } catch (error) {
      console.error("Error selecting conversation:", error);
    }
  };

  // FIX #3: Track last URL-driven fetch to prevent duplicate dispatches
  const lastUrlFetchRef = useRef<string | null>(null);
  
  useEffect(() => {
    // FIX #3: Use ref to track what we've already dispatched for this URL state.
    // This prevents the race where handleSelectConversation dispatches setActiveConversation
    // + fetchMessages, then the URL updates, and this effect fires again causing a
    // duplicate fetch for the same conversation.
    if (routeConversationId && routeConversationId !== lastUrlFetchRef.current) {
      const currentActiveId = activeConversationIdRef.current;
      
      // Only dispatch if Redux doesn't already have this conversation active
      if (currentActiveId !== routeConversationId) {
        console.log(`Setting active conversation from URL: ${routeConversationId}`);
        dispatch(setActiveConversation(routeConversationId));
        dispatch(fetchMessages(routeConversationId));
      }
      
      // Mark this URL as fetched
      lastUrlFetchRef.current = routeConversationId;
    }
  }, [routeConversationId, dispatch]);

  return (
    <Box sx={{ width: '100%', maxWidth: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Tabs */}
      <Tabs
        value={leftDrawerTab}
        onChange={(_, newValue) => setLeftDrawerTab(newValue)}
        variant="fullWidth"
        sx={{
          borderBottom: 1,
          borderColor: 'rgba(255,255,255,0.06)',
          background: 'rgba(18,18,22,0.3)',
          backdropFilter: 'blur(12px) saturate(160%)',
          WebkitBackdropFilter: 'blur(12px) saturate(160%)',
          '& .MuiTab-root': {
            minWidth: 0,
            fontSize: '0.7rem',
            textTransform: 'none',
            padding: '8px 4px',
            flex: 1,
            maxWidth: 'none',
            color: 'rgba(255,255,255,0.45)',
            fontWeight: 500,
            '&.Mui-selected': { color: '#c09c58' },
          },
          '& .MuiTabs-indicator': {
            backgroundColor: '#c09c58',
            height: 2,
          },
        }}
      >
        <Tab label="Conversations" />
        <Tab label="Observatory" />
        <Tab label="System" />
      </Tabs>

      {/* Tab Panel 0: Conversations */}
      {leftDrawerTab === 0 && (
        <Box sx={{ flexGrow: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          {/* Session Switcher — V1PRD §4 */}
          <SessionSwitcher
            activeSession={activeSession}
            onActiveSessionChange={onActiveSessionChange}
            onSessionsChanged={onSessionsChanged}
          />
          <Box sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            px: 2,
            py: 1.5,
          }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, fontSize: '0.9rem', letterSpacing: '0.02em' }}>Conversations</Typography>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={onNewChat}
              size="small"
              sx={{
                background: 'rgba(192,156,88,0.12)',
                border: '1px solid rgba(192,156,88,0.2)',
                color: '#c09c58',
                textTransform: 'none',
                fontWeight: 600,
                fontSize: '0.72rem',
                borderRadius: '10px',
                backdropFilter: 'blur(8px)',
                WebkitBackdropFilter: 'blur(8px)',
                '&:hover': {
                  background: 'rgba(192,156,88,0.2)',
                  borderColor: 'rgba(192,156,88,0.35)',
                },
              }}
            >
              New Chat
            </Button>
          </Box>
          <Divider />
      
      {isLoading && allConversations.length === 0 ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          <CircularProgress size={24} />
        </Box>
      ) : allConversations.length > 0 ? (
        <List>
          {allConversations.map(conversation => (
            <ListItemButton 
              key={conversation.id}
              selected={conversation.id === activeConversationId}
              onClick={() => handleSelectConversation(conversation.id)}
              onContextMenu={(e) => handleContextMenu(e, conversation.id)}
              sx={{
                borderRadius: '10px',
                my: 0.25,
                mx: 1,
                px: 2,
                transition: 'all 0.15s ease',
                '&.Mui-selected': {
                  backgroundColor: 'rgba(192,156,88,0.1)',
                  border: '1px solid rgba(192,156,88,0.2)',
                  '&:hover': {
                    backgroundColor: 'rgba(192,156,88,0.15)',
                  }
                },
                '&:hover': {
                  backgroundColor: 'rgba(255,255,255,0.03)',
                }
              }}
            >
              <ListItemIcon>
                <ChatIcon color={conversation.id === activeConversationId ? "primary" : "inherit"} />
              </ListItemIcon>
              <ListItemText
                primary={conversation.title || "New Conversation"}
                secondary={typeof conversation.last_message === 'string' ? conversation.last_message : "No messages yet"}
                sx={{
                  '& .MuiListItemText-primary': {
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    fontWeight: conversation.id === activeConversationId ? 'bold' : 'normal'
                  },
                  '& .MuiListItemText-secondary': {
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    fontSize: '0.75rem'  // Equivalent to 'caption' variant
                  }
                }}
              />
            </ListItemButton>
          ))}
        </List>
      ) : (
        <Box sx={{ p: 2, textAlign: 'center' }}>
          <Typography color="text.secondary">No conversations yet</Typography>
          <Button 
            variant="outlined" 
            startIcon={<AddIcon />} 
            onClick={onNewChat}
            sx={{ mt: 2 }}
          >
            Start a new chat
          </Button>
        </Box>
      )}
      
      {/* Context Menu */}
      <Menu
        open={contextMenu !== null}
        onClose={handleCloseContextMenu}
        anchorReference="anchorPosition"
        anchorPosition={
          contextMenu !== null
            ? { top: contextMenu.mouseY, left: contextMenu.mouseX }
            : undefined
        }
      >
        <MenuItem onClick={handleRenameOption}>
          <ListItemIcon>
            <EditIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Rename conversation</ListItemText>
        </MenuItem>
        <MenuItem onClick={handleDeleteOption}>
          <ListItemIcon>
            <DeleteIcon fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText>Delete conversation</ListItemText>
        </MenuItem>
      </Menu>
      
      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteDialog !== null}
        onClose={handleCancelDelete}
      >
        <DialogTitle>Delete conversation?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to delete &quot;{deleteDialog?.title}&quot;? This action cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelDelete}>Cancel</Button>
          <Button onClick={handleConfirmDelete} color="error" variant="contained">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
      
      {/* Rename Dialog */}
      <Dialog
        open={renameDialog !== null}
        onClose={handleCancelRename}
      >
        <DialogTitle>Rename conversation</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            Enter a new name for this conversation.
          </DialogContentText>
          <TextField
            autoFocus
            margin="dense"
            id="name"
            label="Conversation Name"
            type="text"
            fullWidth
            variant="outlined"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            inputProps={{ maxLength: 100 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelRename}>Cancel</Button>
          <Button 
            onClick={handleConfirmRename} 
            color="primary" 
            variant="contained"
            disabled={!newTitle.trim()}
          >
            Rename
          </Button>
        </DialogActions>
      </Dialog>
        </Box>
      )}

      {/* Tab Panel 1: Neural Observatory */}
      {leftDrawerTab === 1 && (
        <Box sx={{ flexGrow: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <NeuralSidebar
            emotion={emotion}
            memories={memories}
            onRefreshMemories={onRefreshMemories}
          />
        </Box>
      )}

      {/* Tab Panel 2: System Debug */}
      {leftDrawerTab === 2 && (
        <Box sx={{ flexGrow: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%', width: '100%' }}>
          <SystemDebugPanel />
        </Box>
      )}
    </Box>
  );
});

// FAISS activity indicator component
const FAISSActivityIndicator = () => {
  const [active, setActive] = useState(false);
  
  // Listen for FAISS activity events from the server
  useEffect(() => {
    const handleFAISSActivity = (data: { active: boolean }) => {
      setActive(data.active);
      
      // Auto-reset after 3 seconds if active
      if (data.active) {
        setTimeout(() => setActive(false), 3000);
      }
    };
    
    const unsubscribe = socketService.onFAISSActivity(handleFAISSActivity);
    return unsubscribe;
  }, []);
  
  if (!active) return null;
  
  return (
    <Box sx={{ 
      position: 'fixed',
      top: 70,
      right: 20,
      zIndex: 1500,
      display: 'flex',
      alignItems: 'center',
      background: 'rgba(14, 14, 18, 0.75)',
      backdropFilter: 'blur(20px) saturate(180%)',
      WebkitBackdropFilter: 'blur(20px) saturate(180%)',
      borderRadius: '12px',
      padding: '6px 12px',
      boxShadow: '0 8px 24px rgba(0, 0, 0, 0.3)',
      border: '1px solid rgba(255,255,255,0.06)',
    }}>
      <Box sx={{ 
        width: 12, 
        height: 12, 
        borderRadius: '50%',
        bgcolor: '#4CAF50',
        mr: 1,
        animation: 'pulse 1.5s infinite',
        '@keyframes pulse': {
          '0%': { opacity: 1 },
          '50%': { opacity: 0.4 },
          '100%': { opacity: 1 },
        }
      }} />
      <Typography variant="caption" sx={{ fontWeight: 500 }}>
        FAISS Search Active
      </Typography>
    </Box>
  );
};

// Define message type to replace any
interface Message {
  id: string;
  content: string;
  role: string;
  timestamp: string;
  conversationId: string;
  turnMeta?: { deep_reasoning: boolean; tier: string; route: string | null };
}

// Add this new component that will display model thinking in chat
interface ModelThinkingDisplayProps {
  visible: boolean;
  activeTabIndex?: number;
}

const ModelThinkingDisplay = ({ visible, activeTabIndex = 0 }: ModelThinkingDisplayProps) => {
  const [activeTab, setActiveTab] = useState(activeTabIndex);
  const [streams] = useState({ l1: '', l2: '', l3: '' });
  
  if (!visible) return null;
  
  const streamTypes = ['l1', 'l2', 'l3'] as const;
  const streamContent = streams[streamTypes[activeTab]];
  
  return (
    <Box sx={{ 
      position: 'absolute',
      bottom: '80px',
      left: 0,
      right: 0,
      zIndex: 10,
      maxHeight: '40vh',
      overflow: 'auto',
      backgroundColor: 'rgba(14,14,18,0.78)',
      backdropFilter: 'blur(20px) saturate(180%)',
      WebkitBackdropFilter: 'blur(20px) saturate(180%)',
      borderTop: '1px solid rgba(255,255,255,0.06)',
      display: 'flex',
      flexDirection: 'column'
    }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', padding: 1, borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
        <Tabs
          value={activeTab}
          onChange={(_, newValue) => setActiveTab(newValue)}
          variant="scrollable"
          scrollButtons="auto"
        >
          <Tab label="L1: Instinct" />
          <Tab label="L2: Reasoning" />
          <Tab label="L3: Synthesis" />
        </Tabs>
      </Box>
      <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
        <StreamingVisualizer content={streamContent} height="100%" />
      </Box>
    </Box>
  );
};

export default function ChatPage() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const router = useRouter();
  const conversationId = router.query.id as string;
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  // Add a ref to track if we've already joined this conversation
  const hasJoinedConversation = useRef<string | null>(null);
  
  // Create one-time initialization flag
  const isInitialMount = useRef(true);
  
  // Socket.IO removed - using direct API calls via useSocket for emotion updates
  useSocket();
  
  // Use server status for connection check (HTTP availability, not Socket.IO)
  const { isServerAvailable } = useServerStatus();
  const isConnected = isServerAvailable;  // Backend is available via HTTP
  
  // Get user settings for commander identity
  const { settings } = useSettings();
  const commanderIdentity = settings.commanderIdentity || "Mai";

  // System State Machine UI
  const [systemState, setSystemState] = useState<{
    state: 'ACTIVE' | 'IDLE' | 'DREAMING' | 'SLEEPING';
    state_updated_at: string;
    last_user_interaction: string;
    last_active_user_id: string;
    session_started_at: string;
    idle_after_minutes: number;
    dream_after_minutes: number;
    wake_word: string;
    auto_wake_on_query: boolean;
    dreaming_task_running: boolean;
  } | null>(null);
  const [systemStateLoading, setSystemStateLoading] = useState(false);
  const [systemActionLoading, setSystemActionLoading] = useState<'sleep' | 'wake' | null>(null);
  
  const dispatch = useAppDispatch();
  const messages = useAppSelector(state => Array.isArray(state.chat.messages) ? state.chat.messages : []);
  const isLoading = useAppSelector(state => state.chat.isLoading);
  const streamingResponse = useAppSelector(state => state.chat.streamingResponse);
  const streamedContent = useAppSelector(state => state.chat.streamedContent);
  const activeConversationId = useAppSelector(state => state.chat.activeConversationId);

  // Debug features for showing model thinking process
  const [debugStreams, setDebugStreams] = useState({ l1: '', l2: '', l3: '' });
  const [isDebugPanelOpen, setIsDebugPanelOpen] = useState(false);
  
  const toggleDebugPanel = () => setIsDebugPanelOpen(!isDebugPanelOpen);
  const updateDebugStream = useCallback((layer: 'l1' | 'l2' | 'l3', content: string) => {
    setDebugStreams(prev => ({ ...prev, [layer]: content }));
  }, []);
  
  // Set default to true for non-mobile, so it's open by default
  const [leftDrawerOpen, setLeftDrawerOpen] = useState(!isMobile);
  
  // Goal pursuit modal state
  const [goalPursuitModal, setGoalPursuitModal] = useState<{
    open: boolean;
    goal: Goal | null;
  }>({
    open: false,
    goal: null,
  });
  // System restart modal state (for self-modification safety)
  const [restartModalOpen, setRestartModalOpen] = useState(false);
  const [restartModifiedPath, setRestartModifiedPath] = useState<string | null>(null);
  
  // TTS State
  const [isTTSEnabled, setIsTTSEnabled] = useState(false);
  const [selectedVoice, setSelectedVoice] = useState('en-US-MichelleNeural');
  const [ttsProvider, setTtsProvider] = useState<'edge' | 'qwen3' | 'fishaudio'>('edge');
  const [voiceMenuAnchor, setVoiceMenuAnchor] = useState<null | HTMLElement>(null);
  const [qwen3Available, setQwen3Available] = useState<boolean | null>(null);
  const [fishaudioAvailable, setFishaudioAvailable] = useState<boolean | null>(null);

  // Model Stack State (0=default, 1=stack1, 2=stack2)
  const [modelStackIndex, setModelStackIndex] = useState(0);
  const [modelStackLoading, setModelStackLoading] = useState(false);
  
  // P2-42: no reasoning toggles. The tier slider and the L1 route decide how much Aura thinks.
  const activeTier = useActiveTier();

  // Cognitive Telemetry modal (L1/L2/L3 trace feed)
  const [telemetryOpen, setTelemetryOpen] = useState(false);

  // Chart dialog state
  const [chartDialogConfig, setChartDialogConfig] = useState<ChartJsConfig | null>(null);

  // Memory graph dialog state
  const [graphDialogOpen, setGraphDialogOpen] = useState(false);

  // Session state — V1PRD §4
  const [activeSession, setActiveSession] = useState<Session | null>(null);

  // Neural Observatory State
  const [emotion, setEmotion] = useState<EmotionState>({
    love: 0.2, joy: 0.3, interest: 0.4, trust: 0.3, fear: 0.1,
    sadness: 0.1, anger: 0.0, surprise: 0.1, disgust: 0.0,
    awe: 0.2, beauty: 0.15, wonder: 0.25, serenity: 0.2,
    melancholy: 0.1, nostalgia: 0.1, empathy: 0.3, gratitude: 0.2,
    pride: 0.1, shame: 0.0, envy: 0.0, compassion: 0.25,
    curiosity: 0.4, confusion: 0.1, certainty: 0.2, doubt: 0.1,
    fascination: 0.3, boredom: 0.0,
    current_state: "CURIOSITY",
    dominant: "curiosity",
    valence: 0.3,
    arousal: 0.4,
    entropy: 0.15,
  });
  const [memories, setMemories] = useState<Memory[]>([]);

  // Avatar cognitive state from socket avatar_state events
  const [avatarCognitiveState, setAvatarCognitiveState] = useState<string>("attending");

  // Check Qwen3-TTS and FishAudio availability on mount and periodically
  useEffect(() => {
    const checkTTS = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/voice/status`);
        if (res.ok) {
          const data = await res.json();
          setQwen3Available(data.qwen3_available === true);
          setFishaudioAvailable(data.fishaudio_available === true);
        }
      } catch (e) {
        console.debug('TTS status check failed:', e);
        setQwen3Available(false);
        setFishaudioAvailable(false);
      }
    };
    checkTTS();
    const interval = setInterval(checkTTS, 30000);
    return () => clearInterval(interval);
  }, []);

  // Fetch current model stack on mount
  useEffect(() => {
    const fetchModelStack = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/system/model-stack`);
        if (res.ok) {
          const data = await res.json();
          setModelStackIndex(data.stack_index);
        }
      } catch (e) {
        console.debug('Model stack fetch failed:', e);
      }
    };
    fetchModelStack();
  }, []);

  // Switch model stack
  const switchModelStack = useCallback(async (index: number) => {
    setModelStackLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/system/model-stack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stack_index: index }),
      });
      if (res.ok) {
        const data = await res.json();
        setModelStackIndex(data.current_stack);
      }
    } catch (e) {
      console.error('Failed to switch model stack:', e);
    } finally {
      setModelStackLoading(false);
    }
  }, []);

  // Edge-TTS voices
  const edgeTTSVoices = [
    { id: 'en-US-AriaNeural', name: 'Aria (US Female, Friendly)' },
    { id: 'en-US-GuyNeural', name: 'Guy (US Male, Casual)' },
    { id: 'en-US-JennyNeural', name: 'Jenny (US Female, Assistant)' },
    { id: 'en-US-EricNeural', name: 'Eric (US Male, News)' },
    { id: 'en-US-MichelleNeural', name: 'Michelle (US Female, Expressive)' },
    { id: 'en-GB-SoniaNeural', name: 'Sonia (British Female)' },
    { id: 'en-GB-RyanNeural', name: 'Ryan (British Male)' },
    { id: 'en-AU-NatashaNeural', name: 'Natasha (Australian Female)' },
    { id: 'en-AU-WilliamNeural', name: 'William (Australian Male)' },
  ];

  const toggleTTS = useCallback(() => {
    setIsTTSEnabled(prev => !prev);
  }, []);

  const handleVoiceMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setVoiceMenuAnchor(event.currentTarget);
  };

  const handleVoiceMenuClose = () => {
    setVoiceMenuAnchor(null);
  };

  const handleVoiceSelect = (voice: string) => {
    setSelectedVoice(voice);
    handleVoiceMenuClose();
  };

  const handleProviderSwitch = (provider: 'edge' | 'qwen3' | 'fishaudio') => {
    setTtsProvider(provider);
    if (provider === 'qwen3') {
      setSelectedVoice('serena');
    } else if (provider === 'fishaudio') {
      setSelectedVoice('default');
    } else if (provider === 'edge' && !selectedVoice.endsWith('Neural')) {
      setSelectedVoice('en-US-MichelleNeural');
    }
  };

  // Fetch emotion state
  const fetchEmotionState = useCallback(async () => {
    try {
      const emotionData = await auraApi.getEmotionState();
      setEmotion(emotionData);
    } catch (error) {
      console.error('Failed to fetch emotion state:', error);
    }
  }, []);

  const fetchSystemState = useCallback(async () => {
    try {
      setSystemStateLoading(true);
      const state = await auraApi.getSystemState();
      setSystemState(state);
    } catch (error) {
      console.error('Failed to fetch system state:', error);
    } finally {
      setSystemStateLoading(false);
    }
  }, []);

  const handleForceSleep = useCallback(async () => {
    try {
      setSystemActionLoading('sleep');
      // Force sleep for this user (commander identity)
      const state = await auraApi.sleepSystem(commanderIdentity);
      setSystemState(state);
      dispatch(addMessage({
        id: Date.now().toString() + '_system_sleep',
        content: 'Entering sleep mode (dreaming + consolidation)...',
        role: 'system',
        timestamp: new Date().toISOString(),
        conversationId: conversationId || 'temp',
      }));
    } catch (error) {
      console.error('Failed to force sleep:', error);
      dispatch(addMessage({
        id: Date.now().toString() + '_system_sleep_error',
        content: `❌ Failed to enter sleep: ${error instanceof Error ? error.message : 'Unknown error'}`,
        role: 'system',
        timestamp: new Date().toISOString(),
        conversationId: conversationId || 'temp',
      }));
    } finally {
      setSystemActionLoading(null);
    }
  }, [commanderIdentity, dispatch, conversationId]);

  const handleForceWake = useCallback(async () => {
    try {
      setSystemActionLoading('wake');
      const result = await auraApi.wakeSystem(commanderIdentity);
      setSystemState(result.state);
      if (result.greeting) {
        dispatch(addMessage({
          id: Date.now().toString() + '_system_wake',
          content: result.greeting,
          role: 'system',
          timestamp: new Date().toISOString(),
          conversationId: conversationId || 'temp',
        }));
      }
    } catch (error) {
      console.error('Failed to force wake:', error);
      dispatch(addMessage({
        id: Date.now().toString() + '_system_wake_error',
        content: `❌ Failed to wake system: ${error instanceof Error ? error.message : 'Unknown error'}`,
        role: 'system',
        timestamp: new Date().toISOString(),
        conversationId: conversationId || 'temp',
      }));
    } finally {
      setSystemActionLoading(null);
    }
  }, [commanderIdentity, dispatch, conversationId]);
  
  // Fetch memories
  const fetchMemories = useCallback(async () => {
    try {
      console.log('[CHAT PAGE] Fetching memories for user:', commanderIdentity);
      const memoriesData = await auraApi.getRecentMemories(100, commanderIdentity);
      console.log('[CHAT PAGE] Memories fetched:', memoriesData.length, 'memories');
      setMemories(memoriesData);
    } catch (error) {
      console.error('[CHAT PAGE] Failed to fetch memories:', error);
    }
  }, [commanderIdentity]);
  
  // Helper function to fetch and join a conversation - wrap in useCallback
  // FIX #6: Check conversation exists BEFORE setting it as active
  const fetchAndJoinConversation = useCallback((id: string) => {
    if (!id) return;
    
    console.log(`Fetching conversation: ${id}`);
    
    // FIX #6: First verify the conversation exists, THEN set as active
    apiService.getConversation(id)
      .then(conversation => {
        console.log(`Successfully loaded conversation: ${conversation.title}`);
        
        // Now safe to set as active since we confirmed it exists
        dispatch(setActiveConversation(id));
        
        // Fetch messages
        dispatch(fetchMessages(id));
      })
      .catch((error: Error) => {
        console.error(`Failed to load conversation ${id}:`, error);
        // If we can't load the conversation, try to navigate to home
        if (router.pathname === '/chat') {
          router.push('/chat', undefined, { shallow: true });
        }
      });
  }, [dispatch, router]);
  
  // Load conversation when ID changes
  useEffect(() => {
    if (conversationId && hasJoinedConversation.current !== conversationId) {
      console.log(`Loading conversation: ${conversationId}`);
      
      // Update the ref to track that we've loaded this conversation
      hasJoinedConversation.current = conversationId;
      
      // Set active conversation in Redux
      dispatch(setActiveConversation(conversationId));
      
      // Fetch messages for this conversation (fetchMessages.fulfilled replaces state.messages,
      // so there's no need to clearMessages first — that only causes a blank flash + race conditions)
      dispatch(fetchMessages(conversationId)).catch((error) => {
        // FIX #4: Reset the ref on error so the next attempt will retry
        console.error(`Failed to fetch messages for ${conversationId}:`, error);
        hasJoinedConversation.current = null;
      });
    } else if (!conversationId) {
      // If we don't have a conversation ID, clear messages
      console.log('No active conversation, clearing messages');
      dispatch(clearMessages());
      
      // Reset the loaded conversation tracking
      hasJoinedConversation.current = null;
    }
    
    // Fetch emotion and memories on mount
    // FIX #7: isInitialMount flag is now set in a dedicated useEffect below.
    // This block is kept for backward compatibility but the flag check is
    // no longer needed since the dedicated effect handles one-time initialization.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, dispatch, activeConversationId, fetchEmotionState, fetchMemories]);
  
  // FIX #7: Atomic initial mount — single effect handles the one-time setup.
  // This prevents race conditions where multiple effects could read isInitialMount
  // as true before any of them set it to false. By consolidating into one effect
  // with empty deps, we guarantee this runs exactly once on mount.
  const hasDoneInitialSetup = useRef(false);
  
  useEffect(() => {
    if (!hasDoneInitialSetup.current) {
      hasDoneInitialSetup.current = true;
      isInitialMount.current = false; // Mark as no longer initial
      
      fetchEmotionState();
      fetchMemories();
      fetchSystemState();
    }
  }, []); // Empty deps — runs once on mount

  // Fetch main session on mount
  useEffect(() => {
    sessionService.get("main").then(s => {
      if (s) setActiveSession(s);
    }).catch(() => {
      // Main session may not exist yet if migration hasn't run; that's fine
    });
  }, []);

  // Poll system state occasionally (kept light to avoid UI jitter)
  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | null = null;
    if (!document.hidden) {
      intervalId = setInterval(() => {
        if (!document.hidden) {
          fetchSystemState();
        }
      }, 30000); // 30s
    }
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [fetchSystemState]);
  
  // Handle streaming tokens from different models
  useEffect(() => {
    const handleStreamToken = (data: StreamTokenData) => {
      const { type, token, conversation_id, agent_id } = data;
      
      // Log agent ID and conversation ID relationship
      if (agent_id && conversation_id) {
        console.log(`Stream data received - Agent ID: ${agent_id}, Conversation ID: ${conversation_id}`);
      }
      
      // Only process tokens for the current conversation
      if (!conversationId || conversation_id !== conversationId) {
        return;
      }
      
      // Note: Streaming is now handled by the Aura API directly
      // This socket-based streaming is kept for backward compatibility
      // but may not be actively used with the new Aura backend
      
      // Update debug streams if needed (currently not used)
      console.log(`Received stream token from ${type}:`, token);
    };
    
    // Set up socket listeners for streaming
    const streamTokenUnsubscribe = socketService.onStreamToken(handleStreamToken);
    
    // Set up socket listener for stream end
    const streamEndUnsubscribe = socketService.onStreamEnd((data: {
      error?: string;
      cancelled?: boolean;
      conversation_id?: string;
    }) => {
      if (data.error) {
        console.error('Stream error:', data.error);
      } else if (!data.cancelled && conversationId === data.conversation_id) {
        dispatch(endStreamingResponse());
      }
    });
    
    return () => {
      streamTokenUnsubscribe();
      streamEndUnsubscribe();
    };
  }, [dispatch, conversationId, streamingResponse, updateDebugStream, debugStreams]);
  
  // Handle chat messages separately to avoid dependency issues
  useEffect(() => {
    // Handle incoming chat message
    const handleChatMessage = (message: {
      id: string;
      content: string;
      role: string;
      timestamp: string;
      conversationId: string;
    }) => {
      console.log('Received chat message:', message);
      if (message.conversationId === conversationId) {
        // Check if this message already exists in our messages array
        const messageExists = Array.isArray(messages) && 
          messages.some(m => m.id === message.id);
        
        if (!messageExists) {
          dispatch(addMessage(message));
        }
      }
    };
    
    const chatMessageUnsubscribe = socketService.onChatMessage(handleChatMessage);
    
    return () => {
      chatMessageUnsubscribe();
    };
  }, [dispatch, conversationId, messages]);

  // Subscribe to avatar_state socket events to drive the cognitive layer
  useEffect(() => {
    if (typeof process === "undefined" || process.env.NEXT_PUBLIC_AVATAR_STAGE !== "1") {
      return undefined;
    }
    const unsubscribe = socketService.onAvatarState((data) => {
      setAvatarCognitiveState(data.cognitive_state);
    });
    return unsubscribe;
  }, []);
  
  // Scroll to bottom when messages change or streaming content updates
  // Debounced scroll to avoid thrashing during streaming
  useEffect(() => {
    const scrollContainer = messagesEndRef.current;
    if (scrollContainer) {
      // Use requestAnimationFrame for smoother scrolling during high-frequency updates
      requestAnimationFrame(() => {
        scrollContainer.scrollIntoView({ behavior: 'smooth' });
      });
    }
  }, [messages, streamedContent]);
  
  // Check for goal pursuit request marker in Aura's response
  const checkForGoalPursuitRequest = useCallback(async (responseText: string) => {
    // Look for the marker: [GOAL_PURSUIT_REQUEST:goal_id]
    const match = responseText.match(/\[GOAL_PURSUIT_REQUEST:([^\]]+)\]/);
    if (match) {
      const goalId = match[1];
      
      // Fetch the goal to show in modal
      try {
        const goals = await auraApi.getActiveGoals();
        let goal = goals.find(g => g.goal_id === goalId);
        
        // Fallback: If exact ID match fails, try to match by name (resilient to LLM hallucinations)
        if (!goal) {
          // The LLM might use "goal:goal_name_snake_case" instead of the UUID
          // Example: goal:review_recent_learnings -> review recent learnings
          const potentialNamePart = goalId.replace(/^goal:/, '').replace(/_/g, ' ').toLowerCase();
          
          goal = goals.find(g => {
            const goalName = g.name.toLowerCase();
            return goalName === potentialNamePart || 
                   goalName.includes(potentialNamePart) || 
                   potentialNamePart.includes(goalName);
          });
          
          if (goal) {
            console.log(`Goal matched by name fallback: ${goalId} -> ${goal.goal_id} (${goal.name})`);
          }
        }
        
        if (goal) {
          setGoalPursuitModal({
            open: true,
            goal: goal,
          });
        } else {
          console.warn(`Goal ${goalId} not found in active goals`);
        }
      } catch (error) {
        console.error('Error fetching goal for pursuit request:', error);
      }
    }
  }, []);

  // Check for restart-required marker in Aura's response (self-modification safety)
  const checkForRestartRequired = useCallback((responseText: string) => {
    const match = responseText.match(/\[RESTART_REQUIRED:([^\]]+)\]/);
    if (match) {
      const path = match[1];
      setRestartModifiedPath(path);
      setRestartModalOpen(true);
    }
  }, []);
  
  // Handle goal pursuit confirmation
  const handleGoalPursuitConfirm = useCallback(async (
    goalId: string,
    loopCount: number,
    toolPermissions: string[],
    allowInterruption: boolean
  ) => {
    // Close the modal immediately before starting the process if interruptible
    // For non-interruptible, we might want to keep it open or show a progress indicator (future improvement)
    setGoalPursuitModal(prev => ({ ...prev, open: false }));

    // Show starting message
    const startMessage: Message = {
      id: Date.now().toString() + '_pursuit_start',
      content: `🚀 Starting autonomous pursuit of goal... (${loopCount} cycles)`,
      role: 'system',
      timestamp: new Date().toISOString(),
      conversationId: conversationId || 'temp',
    };
    dispatch(addMessage(startMessage));

    try {
      const result = await auraApi.pursueGoal(goalId, loopCount, toolPermissions, allowInterruption);
      
      if (result && result.success) {
        // Add a message showing the pursuit results
        const pursuitMessage: Message = {
          id: Date.now().toString() + '_pursuit',
          content: `✅ Autonomous pursuit complete: ${result.goal_name}\n` +
                   `Progress: ${Math.round(result.initial_progress * 100)}% → ${Math.round(result.final_progress * 100)}% ` +
                   `(+${Math.round(result.progress_delta * 100)}%)\n` +
                   `Completed ${result.loop_count} reasoning cycles.`,
          role: 'system',
          timestamp: new Date().toISOString(),
          conversationId: conversationId || 'temp',
        };
        
        dispatch(addMessage(pursuitMessage));
      } else {
        throw new Error('Goal pursuit failed');
      }
    } catch (error) {
      console.error('Error pursuing goal:', error);
      // Add error message
      const errorMessage: Message = {
        id: Date.now().toString() + '_pursuit_error',
        content: `❌ Failed to pursue goal autonomously: ${error instanceof Error ? error.message : 'Unknown error'}`,
        role: 'system',
        timestamp: new Date().toISOString(),
        conversationId: conversationId || 'temp',
      };
      dispatch(addMessage(errorMessage));
    }
  }, [conversationId, dispatch]);

  const handleSendMessage = useCallback(async (content: string) => {
    if (!content.trim()) return;
    
    try {
      // Add the user message to the state
      const userMessage: Message = {
        id: Date.now().toString(),
        content,
        role: 'user',
        timestamp: new Date().toISOString(),
        conversationId: conversationId || 'temp'
      };
      
      // Make sure messages is an array before dispatching
      if (!Array.isArray(messages)) {
        dispatch(clearMessages());
      }
      
      // Add to Redux state for immediate UI update
      dispatch(addMessage(userMessage));
      
      // Start streaming response
      dispatch(startStreamingResponse());
      
      // Build conversation history from Redux messages
      // Format: [{ role: 'user' | 'assistant', content: string }]
      // Exclude the current message since it will be sent as user_input separately
      // Filter to only include messages before the one we just added
      const conversationHistory = messages
        .filter((msg, index) => {
          // Exclude the last message if it's the current user message we just added
          if (index === messages.length - 1 && msg.role === 'user' && msg.content === content) {
            return false;
          }
          return msg.role === 'user' || msg.role === 'assistant';
        })
        .map(msg => ({
          role: msg.role === 'assistant' ? 'assistant' : 'user',
          content: msg.content
        }));
      
      // Log for debugging
      // console.log(`📤 Sending message with ${conversationHistory.length} messages in conversation history`);
      
      // Streaming TTS state
      const textBuffer = { current: '' };
      const audioQueue: Blob[] = [];
      const isPlaying = { current: false };

      // --- FIFO Sentence Queue: prevents async racing where shorter sentences
      //     resolve before longer preceding ones, causing out-of-order playback.
      const sentenceQueue: string[] = [];
      let isProcessingQueue = false;

      const processSentenceQueue = async () => {
        if (isProcessingQueue) return;
        isProcessingQueue = true;
        while (sentenceQueue.length > 0) {
          const sentence = sentenceQueue.shift()!;
          await generateAudioForSentence(sentence);
        }
        isProcessingQueue = false;
      };
      // -------------------------------------------------------------------
      
      // Sentence detection regex — matches .!? followed by whitespace or end
      const sentenceEndRegex = /[.!?]\s+$/;
      
      // Text sanitization function — must mirror the backend's strip_emojis() so we
      // don't send emoji-only sentences that the backend would reject with a 400.
      const sanitizeText = (text: string): string => {
        return text
          .replace(/\*/g, '')                  // Remove asterisks but keep content: *smiles* → smiles
          .replace(/[()]/g, '')                // Remove parentheses but keep content: (quietly) → quietly
          .replace(/[_]{1,2}/g, '')            // Remove underscores: _italic_ → italic
          // Strip emoji (Emoji_Presentation + common symbol ranges) — mirrors backend strip_emojis()
          .replace(/\p{Emoji_Presentation}/gu, '')
          .replace(/[\u{1F900}-\u{1FAFF}]/gu, '') // Supplemental symbols
          .replace(/[\u{2600}-\u{26FF}]/gu, '')    // Misc symbols
          .replace(/[\u{2700}-\u{27BF}]/gu, '')    // Dingbats
          .replace(/\s+/g, ' ')                // Collapse leftover whitespace
          .trim();
      };
      
      // Audio queue player with robust error recovery
      const playNextInQueue = () => {
        if (isPlaying.current || audioQueue.length === 0) return;
        
        isPlaying.current = true;
        const audioBlob = audioQueue.shift()!;
        
        // Validate blob before attempting playback
        if (audioBlob.size < 100) {
          console.warn('[TTS] Skipping tiny audio blob:', audioBlob.size, 'bytes');
          isPlaying.current = false;
          playNextInQueue();
          return;
        }
        
        const url = URL.createObjectURL(audioBlob);
        const audio = new Audio(url);
        
        // Set a timeout to prevent stuck audio
        const timeoutId = setTimeout(() => {
          console.warn('[TTS] Audio playback timeout — forcing next');
          URL.revokeObjectURL(url);
          isPlaying.current = false;
          playNextInQueue();
        }, 30000);
        
        audio.onended = () => {
          clearTimeout(timeoutId);
          URL.revokeObjectURL(url);
          isPlaying.current = false;
          playNextInQueue();
        };
        
        audio.onerror = () => {
          clearTimeout(timeoutId);
          console.warn('[TTS] Audio playback error — skipping sentence');
          URL.revokeObjectURL(url);
          isPlaying.current = false;
          playNextInQueue();
        };
        
        audio.play().catch(() => {
          clearTimeout(timeoutId);
          console.warn('[TTS] audio.play() rejected — may need user gesture');
          URL.revokeObjectURL(url);
          isPlaying.current = false;
          playNextInQueue();
        });
      };
      
      // Generate audio for a sentence
      const generateAudioForSentence = async (sentence: string) => {
        if (!isTTSEnabled) return;
        
        const cleaned = sanitizeText(sentence);
        
        // Skip if too short (empty or just punctuation)
        if (cleaned.length < 2) {
          return;
        }
        
        /**
         * Build the voice request payload for the given provider.
         * Sends the FULL 27D emotion vector for optimal emotional TTS control.
         */
        const buildPayload = (provider: 'edge' | 'qwen3' | 'fishaudio'): Record<string, unknown> => {
          const payload: Record<string, unknown> = {
            text: cleaned,
            voice: provider === 'qwen3' ? 'serena' : provider === 'fishaudio' ? 'default' : selectedVoice,
            provider,
          };
          // Always send full emotion state for emotional TTS
          payload.emotion_state = {
            dominant: emotion.dominant || 'neutral',
            valence: emotion.valence || 0,
            arousal: emotion.arousal || 0.5,
            // Pass the full 27D vector so the backend can use emotion_to_tts_params
            vector: {
              love: emotion.love, joy: emotion.joy, interest: emotion.interest,
              trust: emotion.trust, fear: emotion.fear, sadness: emotion.sadness,
              anger: emotion.anger, surprise: emotion.surprise, disgust: emotion.disgust,
              awe: emotion.awe, beauty: emotion.beauty, wonder: emotion.wonder,
              serenity: emotion.serenity, melancholy: emotion.melancholy,
              nostalgia: emotion.nostalgia, empathy: emotion.empathy,
              gratitude: emotion.gratitude, pride: emotion.pride,
              shame: emotion.shame, envy: emotion.envy,
              compassion: emotion.compassion, curiosity: emotion.curiosity,
              confusion: emotion.confusion, certainty: emotion.certainty,
              doubt: emotion.doubt, fascination: emotion.fascination,
              boredom: emotion.boredom,
            },
          };
          return payload;
        };

        /**
         * Execute a single TTS request and return { blob, actualProvider } or null.
         */
        const tryTTS = async (provider: 'edge' | 'qwen3' | 'fishaudio'): Promise<{ blob: Blob; actualProvider: string } | null> => {
          try {
            const voiceResponse = await fetch(`${API_BASE_URL}/voice/stream`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(buildPayload(provider)),
            });

            if (voiceResponse.ok) {
              const blob = await voiceResponse.blob();
              // Validate: skip empty or error responses
              if (blob.size < 100) {
                console.warn(`[TTS] ${provider} returned tiny blob (${blob.size} bytes) — likely error`);
                return null;
              }
              const actualProvider = voiceResponse.headers.get('X-TTS-Provider') || provider;
              console.log(`[TTS] ${provider} OK — ${blob.size} bytes, type=${blob.type}, actual=${actualProvider}`);
              return { blob, actualProvider };
            }
            
            // Try to read error body
            let errorBody = '';
            try { errorBody = await voiceResponse.text(); } catch {}
            console.warn(`[TTS] ${provider} returned HTTP ${voiceResponse.status}: ${errorBody.slice(0, 200)}`);
            return null;
          } catch (err) {
            console.warn(`[TTS] ${provider} request failed:`, err);
            return null;
          }
        };

        // --- Primary attempt with the user-selected provider ---
        let result = await tryTTS(ttsProvider);

        // --- Fallback: if Qwen3-TTS or FishAudio failed, retry with Edge-TTS ---
        if (!result && (ttsProvider === 'qwen3' || ttsProvider === 'fishaudio')) {
          console.warn(`[TTS] ${ttsProvider} unavailable — falling back to Edge-TTS`);
          result = await tryTTS('edge');
        }

        if (result) {
          const { blob, actualProvider } = result;

          // Surface warning if backend fell back silently
          if (ttsProvider !== 'edge' && actualProvider === 'edge') {
            console.warn(`[TTS] Backend fell back from ${ttsProvider} to Edge-TTS`);
          }

          audioQueue.push(blob);
          playNextInQueue();
        } else {
          console.warn('[TTS] All providers failed — no audio for this sentence');
        }
      };
      
      // Buffer for throttled token updates to prevent browser freeze
      let tokenBuffer = '';
      let pendingUpdate: number | null = null;
      
      // Throttled dispatch using requestAnimationFrame (max 60 updates/sec)
      const flushTokens = () => {
        if (tokenBuffer) {
          dispatch(appendStreamToken(tokenBuffer));
          tokenBuffer = '';
        }
        pendingUpdate = null;
      };
      

      // Send to Aura backend and handle streaming response
      // commanderIdentity comes from settings (e.g., "Mai") and is used as user_id for memory storage
      // Use activeConversationId (from Redux state) which is more reliable than router query
      const effectiveConversationId = activeConversationId || conversationId;
      
      console.log('[CHAT] Sending message with conversation_id:', effectiveConversationId);
      
      const response = await auraApi.sendMessage({
        message: content,
        user_id: commanderIdentity,  // Commander identity from settings - used for memory storage
        conversation_id: effectiveConversationId,  // Use Redux state, fallback to router query
        session_id: activeSession?.session_id ?? "main",  // V1PRD §4 — scope chat to active session
        conversation_history: conversationHistory,  // Pass conversation history for context
        context_limit: 50,
        onToken: (token) => {
             // Append token to text buffer for TTS
             textBuffer.current += token;
             
             // Check for sentence end
             if (sentenceEndRegex.test(textBuffer.current)) {
               const sentence = textBuffer.current;
               textBuffer.current = ''; // Reset buffer
               
               // Enqueue sentence for sequential FIFO processing — prevents
               // async racing where shorter chunks resolve before longer ones.
               sentenceQueue.push(sentence);
               processSentenceQueue();
             }
             
             // Buffer token and schedule throttled update for UI
             tokenBuffer += token;
             if (!pendingUpdate) {
               pendingUpdate = requestAnimationFrame(flushTokens);
             }
        }
      });
      
      // Flush any remaining buffered tokens
      if (pendingUpdate) {
        cancelAnimationFrame(pendingUpdate);
      }
      flushTokens();
      
      // Handle the streamed response
      if (response && response.response) {
        // Add assistant message
        const assistantMessage: Message = {
          id: Date.now().toString() + '_assistant',
          content: response.response,
          role: 'assistant',
          timestamp: new Date().toISOString(),
          conversationId: conversationId || 'temp',
          // P2-42: lets the message show a deep-reasoning marker.
          turnMeta: response.tier !== undefined ? {
            deep_reasoning: !!response.deep_reasoning,
            tier: response.tier,
            route: response.route ?? null,
          } : undefined,
        };
        
        dispatch(addMessage(assistantMessage));
        dispatch(endStreamingResponse());
        
        // Handle leftover text in buffer (response ended without punctuation)
        if (textBuffer.current.trim().length > 0) {
          sentenceQueue.push(textBuffer.current);
          await processSentenceQueue();
          // Drain any remaining queued sentences
          while (isProcessingQueue) {
            await new Promise(r => setTimeout(r, 50));
          }
        }
        
        // Check for goal pursuit request and restart-required markers in Aura's response
        checkForGoalPursuitRequest(response.response);
        checkForRestartRequired(response.response);
      }
    } catch (error) {
      console.error("Error sending message:", error);
      dispatch(endStreamingResponse());
    }
  }, [conversationId, activeConversationId, commanderIdentity, messages, dispatch, checkForGoalPursuitRequest, checkForRestartRequired, isTTSEnabled, selectedVoice, ttsProvider, fishaudioAvailable, emotion]);
  
  // Simplify toggle handlers to avoid type issues
  const toggleLeftDrawer = () => {
    setLeftDrawerOpen(!leftDrawerOpen);
  };

  const handleToggleDebugPanel = () => {
    toggleDebugPanel();
  };
  
  // FIX #8: Track mounted state for handleNewChat to prevent dispatch after unmount
  const isNewChatMountedRef = useRef(true);
  
  useEffect(() => {
    isNewChatMountedRef.current = true;
    return () => {
      isNewChatMountedRef.current = false;
    };
  }, []);
  
  const handleNewChat = useCallback(async () => {
    try {
      // Clear messages first to prevent any issues when navigating
      dispatch(clearMessages());
      
      // Create a new conversation with commander identity (no title = backend generates it)
      const newConversation = await apiService.createConversation(undefined, commanderIdentity, activeSession?.session_id ?? "main");
      
      if (!newConversation || !newConversation.id) {
        throw new Error("Failed to create conversation: Invalid response from server");
      }
      
      console.log("Created new conversation:", newConversation);
      
      // Fetch the updated list of conversations from the backend to ensure the sidebar updates
      await dispatch(fetchConversationsAction(commanderIdentity));
      // Set active conversation
      dispatch(setActiveConversation(newConversation.id));
      
      // Navigate to new conversation with the ID in the URL
      await router.push(`/chat?id=${newConversation.id}`, undefined, { shallow: true });
      
    } catch (error) {
      console.error("Failed to create new conversation:", error instanceof Error ? error.message : String(error));
      
      // Ensure we still have empty messages array even if creation failed
      dispatch(clearMessages());
    }
  }, [dispatch, commanderIdentity, router, activeSession?.session_id]);
  
  // Add a ref to track initial setup
  const isInitialSetupDone = useRef(false);

  // Modify the useEffect to prevent reopening closed panels
  useEffect(() => {
    if (!isMobile) {
      // Small delay to ensure proper rendering after initial load
      const timer = setTimeout(() => {
        // Only set these states on first load - use a ref to track this
        if (!isInitialSetupDone.current) {
          setLeftDrawerOpen(true);
          isInitialSetupDone.current = true;
        }
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [isMobile]); // Remove toggleDebugPanel and isDebugPanelOpen from dependencies
  
  // Socket.IO connection disabled - using native WebSocket and Aura API instead
  // Note: The old Socket.IO real-time features are replaced by:
  // 1. Direct API calls to Aura backend via auraApiService
  // 2. Native WebSocket at /ws/emotion for emotion updates
  useEffect(() => {
    // If we have a conversation ID from the URL but not in Redux, fetch it
    // Only do this on initial mount or when these values actually change
    // FIX #7: isInitialMount is now managed by the dedicated effect above.
    // This effect still checks it for backward compatibility.
    if (conversationId &&
        (!activeConversationId || activeConversationId !== conversationId) &&
        isInitialMount.current) {
      console.log(`Initial load with conversation ID from URL: ${conversationId}`);
      fetchAndJoinConversation(conversationId);
    }
    
    return () => {
      // Cleanup if needed
    };
  }, [conversationId, activeConversationId, fetchAndJoinConversation]);

  return (
    <ParticlesBackground disableMouseTracking>
      <Head>
        <title>Chat - Aura AI Agents</title>
        <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no" />
      </Head>
      
      {/* Voice Selection Menu with Provider Switching */}
      <Menu
        anchorEl={voiceMenuAnchor}
        open={Boolean(voiceMenuAnchor)}
        onClose={handleVoiceMenuClose}
        PaperProps={{ sx: { maxHeight: 420, minWidth: 280, bgcolor: 'rgba(14,14,18,0.88)', backdropFilter: 'blur(24px) saturate(180%)', WebkitBackdropFilter: 'blur(24px) saturate(180%)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '14px', boxShadow: '0 16px 48px rgba(0,0,0,0.35)' } }}
      >
        <MenuItem disabled sx={{ opacity: 1, py: 0.5 }}>
          <Box sx={{ display: 'flex', gap: 1, width: '100%' }}>
            <Button
              size="small"
              variant={ttsProvider === 'edge' ? 'contained' : 'outlined'}
              onClick={(e) => { e.stopPropagation(); handleProviderSwitch('edge'); }}
              sx={{ flex: 1, fontSize: '0.7rem', textTransform: 'none' }}
            >
              Edge-TTS
            </Button>
            <Button
              size="small"
              variant={ttsProvider === 'qwen3' ? 'contained' : 'outlined'}
              color="secondary"
              onClick={(e) => { e.stopPropagation(); handleProviderSwitch('qwen3'); }}
              sx={{ flex: 1, fontSize: '0.7rem', textTransform: 'none' }}
            >
              Qwen3-TTS
            </Button>
            <Button
              size="small"
              variant={ttsProvider === 'fishaudio' ? 'contained' : 'outlined'}
              sx={{ flex: 1, fontSize: '0.65rem', textTransform: 'none', bgcolor: ttsProvider === 'fishaudio' ? 'rgba(255,140,0,0.3)' : 'transparent', borderColor: 'rgba(255,140,0,0.5)' }}
              onClick={(e) => { e.stopPropagation(); handleProviderSwitch('fishaudio'); }}
            >
              Fish
            </Button>
          </Box>
        </MenuItem>
        <Divider sx={{ borderColor: 'rgba(255,255,255,0.08)' }} />
        {ttsProvider === 'edge' ? (
          edgeTTSVoices.map((voice) => (
            <MenuItem
              key={voice.id}
              onClick={() => handleVoiceSelect(voice.id)}
              selected={voice.id === selectedVoice}
            >
              {voice.name}
            </MenuItem>
          ))
        ) : ttsProvider === 'qwen3' ? (
          [
            <MenuItem key="qwen-info" disabled sx={{ opacity: 0.7, fontSize: '0.75rem', whiteSpace: 'normal' }}>
              Qwen3-TTS uses emotion-driven synthesis controlled by Aura&apos;s emotional state.
            </MenuItem>,
            <MenuItem
              key="qwen-auto"
              onClick={() => handleVoiceSelect('serena')}
              selected={ttsProvider === 'qwen3'}
            >
              Serena (Auto)
            </MenuItem>
          ]
        ) : (
          [
            <MenuItem key="fish-info" disabled sx={{ opacity: 0.7, fontSize: '0.75rem', whiteSpace: 'normal' }}>
              FishAudio uses fish-speech-1.5 with multi-speaker support and voice cloning.
            </MenuItem>,
            <MenuItem
              key="fish-auto"
              onClick={() => handleVoiceSelect('default')}
              selected={ttsProvider === 'fishaudio'}
            >
              Default (Auto)
            </MenuItem>
          ]
        )}
      </Menu>

      <Box sx={{ 
        display: 'flex', 
        flexDirection: 'column',
        height: '100vh',
        width: '100%',
        bgcolor: 'transparent',
        position: 'relative',
        overflow: 'hidden'
      }}>
        {/* Show connection status alert */}
        <ServerStatusAlert />
        
        {/* FAISS Activity Indicator */}
        <FAISSActivityIndicator />
        
        <Box sx={{ 
          display: 'flex', 
          position: 'relative',
          width: '100%',
          height: '100%',
          flexGrow: 1,
          overflow: 'hidden',
          zIndex: 5 // Above particles but below drawers
        }}>
          {/* Conversation List Drawer */}
          <Drawer
            variant={isMobile ? "temporary" : "persistent"}
            open={leftDrawerOpen}
            onClose={toggleLeftDrawer}
            ModalProps={{
              keepMounted: true,
              hideBackdrop: isMobile ? false : true
            }}
            sx={{
              width: 320,
              flexShrink: 0,
              zIndex: 1300,
              display: 'block',
              position: 'fixed',
              '& .MuiDrawer-paper': {
                width: 320,
                boxSizing: 'border-box',
                borderRight: '1px solid',
                borderColor: 'rgba(255, 255, 255, 0.06)',
                background: 'rgba(14, 14, 18, 0.82)',
                backdropFilter: 'blur(24px) saturate(180%)',
                WebkitBackdropFilter: 'blur(24px) saturate(180%)',
                height: '100%',
                position: 'fixed',
                boxShadow: '8px 0 32px rgba(0, 0, 0, 0.3), inset 0 0 0 1px rgba(255,255,255,0.02)',
                overflowY: 'auto',
                overflowX: 'hidden',
              },
            }}
          >
            <ConversationsList 
              onNewChat={handleNewChat}
              emotion={emotion}
              memories={memories}
              onRefreshMemories={fetchMemories}
              activeSession={activeSession}
              onActiveSessionChange={setActiveSession}
              onSessionsChanged={() => {
                dispatch(fetchConversationsAction(commanderIdentity));
              }}
            />
          </Drawer>
          
          {/* Main Content Container - Proper width calculation */}
          <Box
            component="main"
            sx={{
              display: 'flex',
              flexDirection: 'column',
              flexGrow: 1,
              height: '100%',
              position: 'relative',
              px: { xs: 1, sm: 2 },
              transition: theme.transitions.create(['margin', 'width'], {
                easing: theme.transitions.easing.sharp,
                duration: theme.transitions.duration.leavingScreen,
              }),
              // Set left margin based on drawer state
              marginLeft: leftDrawerOpen && !isMobile ? '320px' : 0,
              // Set right margin based on debug panel state with new width
              marginRight: isDebugPanelOpen && !isMobile ? '350px' : 0,
              width: '100%',
              boxSizing: 'border-box',
              // Use calc for accurate width adjustments only on desktop with new debug panel width
              ...((!isMobile && leftDrawerOpen && isDebugPanelOpen) && {
                width: 'calc(100% - 670px)', // Both open (320px + 350px)
              }),
              ...((!isMobile && leftDrawerOpen && !isDebugPanelOpen) && {
                width: 'calc(100% - 320px)', // Only left open
              }),
              ...((!isMobile && !leftDrawerOpen && isDebugPanelOpen) && {
                width: 'calc(100% - 350px)', // Only right open (new width)
              }),
              ...((!isMobile && !leftDrawerOpen && !isDebugPanelOpen) && {
                width: '100%', // Both closed
              }),
            }}
          >
            {/* App Bar - Fixed position */}
            <Box sx={{
              py: 1.5,
              px: 2,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              borderBottom: '1px solid',
              borderRadius: '0 0 14px 14px',
              borderColor: 'rgba(255, 255, 255, 0.06)',
              background: 'rgba(14, 14, 18, 0.78)',
              backdropFilter: 'blur(24px) saturate(180%)',
              WebkitBackdropFilter: 'blur(24px) saturate(180%)',
              boxShadow: '0 4px 24px rgba(0, 0, 0, 0.25), inset 0 0 0 1px rgba(255,255,255,0.02)',
              position: 'sticky',
              top: 0,
              left: 0,
              right: 0,
              zIndex: 1100
            }}>
              <Box sx={{ 
                display: 'flex', 
                alignItems: 'center'
              }}>
                <IconButton
                  onClick={toggleLeftDrawer}
                  color={leftDrawerOpen ? "primary" : "default"}
                  sx={{
                    background: leftDrawerOpen ? 'rgba(192,156,88,0.08)' : 'rgba(255,255,255,0.02)',
                    border: '1px solid',
                    borderColor: leftDrawerOpen ? 'rgba(192,156,88,0.2)' : 'rgba(255,255,255,0.06)',
                    borderRadius: '10px',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    "&:hover": { background: leftDrawerOpen ? "rgba(192,156,88,0.15)" : "rgba(255,255,255,0.06)" },
                    zIndex: 1200
                  }}
                >
                  <MenuIcon />
                </IconButton>
                <IconButton
                  onClick={() => window.location.href = '/'}
                  color="primary"
                  sx={{
                    ml: { xs: 1, md: 1 },
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.06)',
                    borderRadius: '10px',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    "&:hover": { background: "rgba(255,255,255,0.06)" }
                  }}
                >
                  <HomeIcon />
                </IconButton>

                {/* System Sleep/Wake Controls */}
                <Tooltip
                  title={
                    systemState
                      ? `System: ${systemState.state} (idle>${systemState.idle_after_minutes}m, dream>${systemState.dream_after_minutes}m)`
                      : 'System state: unknown'
                  }
                >
                  <span>
                    <IconButton
                      onClick={() => {
                        // If sleeping/dreaming -> wake, else -> sleep
                        if (systemState?.state === 'SLEEPING' || systemState?.state === 'DREAMING') {
                          handleForceWake();
                        } else {
                          handleForceSleep();
                        }
                      }}
                      disabled={systemActionLoading !== null}
                      color={
                        systemState?.state === 'SLEEPING' || systemState?.state === 'DREAMING'
                          ? 'warning'
                          : 'default'
                      }
                      sx={{
                        ml: { xs: 0.5, md: 1 },
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid rgba(255,255,255,0.06)',
                        borderRadius: '8px',
                        backdropFilter: 'blur(8px)',
                        WebkitBackdropFilter: 'blur(8px)',
                        "&:hover": { background: "rgba(255,255,255,0.06)" }
                      }}
                    >
                      {systemActionLoading ? (
                        <CircularProgress size={18} />
                      ) : ttsProvider === 'fishaudio' ? (
                        <SettingsVoiceIcon fontSize="small" />
                      ) : ttsProvider === 'qwen3' ? (
                        (systemState?.state === 'SLEEPING' || systemState?.state === 'DREAMING') ? (
                          <WbSunnyIcon fontSize="small" />
                        ) : (
                          <BedtimeIcon fontSize="small" />
                        )
                      ) : (
                        <VolumeUpIcon fontSize="small" />
                      )}
                    </IconButton>
                  </span>
                </Tooltip>

                <Tooltip title="Refresh system state">
                  <span>
                    <IconButton
                      onClick={fetchSystemState}
                      disabled={systemStateLoading || systemActionLoading !== null}
                      sx={{
                        ml: { xs: 0.5, md: 0.5 },
                        "&:hover": { background: "rgba(255, 255, 255, 0.1)" }
                      }}
                    >
                      {systemStateLoading ? <CircularProgress size={18} /> : <RefreshIcon fontSize="small" />}
                    </IconButton>
                  </span>
                </Tooltip>

                {/* Aurari Logic Switcher — Glassmorphism 3-State LLM Selector */}
                <Box sx={{
                  display: "flex",
                  ml: 1,
                  mr: 0.5,
                  position: 'relative',
                  '@keyframes auraLogicPulse': {
                    '0%, 100%': {
                      boxShadow: '0 0 15px rgba(245,158,11,0.30)',
                      borderColor: 'rgba(245,158,11,0.40)',
                    },
                    '50%': {
                      boxShadow: '0 0 28px rgba(245,158,11,0.65)',
                      borderColor: 'rgba(245,158,11,0.70)',
                    },
                  },
                  '@keyframes auraDotPing': {
                    '0%': { transform: 'scale(1)', opacity: 1 },
                    '75%, 100%': { transform: 'scale(2.2)', opacity: 0 },
                  },
                }}>
                  {/* Glass Pill Container */}
                  <Box sx={{
                    position: 'relative',
                    display: 'flex',
                    p: '3px',
                    background: 'rgba(255,255,255,0.04)',
                    backdropFilter: 'blur(20px) saturate(180%)',
                    WebkitBackdropFilter: 'blur(20px) saturate(180%)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: '14px',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.35), inset 0 0 0 1px rgba(255,255,255,0.02)',
                  }}>
                    {/* Sliding Active Indicator */}
                    <Box sx={{
                      position: 'absolute',
                      top: 3,
                      bottom: 3,
                      transition: 'all 500ms cubic-bezier(0.4, 0, 0.2, 1)',
                      borderRadius: '11px',
                      ...(modelStackIndex === 0 && {
                        left: 3,
                        width: 'calc(33.333% - 4px)',
                        background: 'rgba(255,255,255,0.08)',
                        border: '1px solid rgba(255,255,255,0.06)',
                      }),
                      ...(modelStackIndex === 1 && {
                        left: 'calc(33.333% + 1px)',
                        width: 'calc(33.333% - 4px)',
                        background: 'rgba(255,255,255,0.12)',
                        border: '1px solid rgba(255,255,255,0.08)',
                      }),
                      ...(modelStackIndex === 2 && {
                        left: 'calc(66.666% + 1px)',
                        width: 'calc(33.333% - 4px)',
                        background: 'rgba(245,158,11,0.18)',
                        border: '1px solid rgba(245,158,11,0.40)',
                        boxShadow: '0 0 15px rgba(245,158,11,0.30)',
                        animation: streamingResponse ? 'auraLogicPulse 2s ease-in-out infinite' : 'none',
                      }),
                    }} />

                    {/* Three Stack Buttons */}
                    {[
                      { id: 0, label: 'Lean', tooltip: 'Daily Driver (800B)' },
                      { id: 1, label: 'Core', tooltip: 'Active Reasoning' },
                      { id: 2, label: 'Titan', tooltip: '3.8T AGI Mode' },
                    ].map((opt) => {
                      const isActive = modelStackIndex === opt.id;
                      const isTitanThinking = isActive && opt.id === 2 && streamingResponse;
                      return (
                        <Tooltip key={opt.id} title={opt.tooltip} arrow>
                          <Button
                            onClick={() => switchModelStack(opt.id)}
                            disabled={modelStackLoading}
                            disableRipple
                            sx={{
                              position: 'relative',
                              zIndex: 10,
                              flex: 1,
                              py: 0.5,
                              minWidth: 0,
                              fontSize: '0.68rem',
                              fontWeight: 600,
                              letterSpacing: '0.03em',
                              textTransform: 'none',
                              color: isActive ? '#fff' : 'rgba(255,255,255,0.40)',
                              borderRadius: '11px',
                              transition: 'color 300ms ease',
                              '&:hover': {
                                color: isActive ? '#fff' : 'rgba(255,255,255,0.72)',
                                background: 'transparent',
                              },
                              '&.Mui-disabled': {
                                color: isActive ? 'rgba(255,255,255,0.50)' : 'rgba(255,255,255,0.25)',
                              },
                            }}
                          >
                            {modelStackLoading && isActive ? (
                              <CircularProgress size={14} sx={{ color: 'inherit' }} />
                            ) : ttsProvider === 'qwen3' ? (
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                {opt.label}
                                {/* Thinking Dot — pulses when Titan is processing */}
                                {isTitanThinking && (
                                  <Box sx={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                    <Box sx={{
                                      width: 5,
                                      height: 5,
                                      borderRadius: '50%',
                                      bgcolor: '#f59e0b',
                                      animation: 'auraDotPing 1.2s cubic-bezier(0, 0, 0.2, 1) infinite',
                                      position: 'absolute',
                                    }} />
                                    <Box sx={{
                                      width: 5,
                                      height: 5,
                                      borderRadius: '50%',
                                      bgcolor: '#f59e0b',
                                    }} />
                                  </Box>
                                )}
                              </Box>
                            ) : (
                              opt.label
                            )}
                          </Button>
                        </Tooltip>
                      );
                    })}
                  </Box>
                </Box>
              </Box>
              
              {/* Center section — Telemetry toggle | Title | Reasoning toggle */}
              <Box sx={{ flexGrow: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>

                {/* Center-Left: Cognitive Telemetry toggle */}
                <Tooltip title={telemetryOpen ? "Close telemetry feed" : "Open Cognitive Telemetry (L1/L2/L3 live traces)"}>
                  <IconButton
                    onClick={() => setTelemetryOpen(v => !v)}
                    color={telemetryOpen ? "primary" : "default"}
                    size="small"
                    sx={{
                      background: telemetryOpen ? 'rgba(34,211,238,0.08)' : 'rgba(255,255,255,0.02)',
                      border: '1px solid',
                      borderColor: telemetryOpen ? 'rgba(34,211,238,0.22)' : 'rgba(255,255,255,0.06)',
                      borderRadius: '8px',
                      backdropFilter: 'blur(8px)',
                      WebkitBackdropFilter: 'blur(8px)',
                      '&:hover': { background: telemetryOpen ? 'rgba(34,211,238,0.15)' : 'rgba(255,255,255,0.06)' },
                    }}
                  >
                    <TimelineIcon sx={{ fontSize: 18, color: telemetryOpen ? '#22d3ee' : 'inherit' }} />
                  </IconButton>
                </Tooltip>

                {/* Center: Aura Status / Conversation title */}
                <Typography variant="h6" sx={{
                  fontWeight: 500,
                  background: 'linear-gradient(90deg, #f5cc7f 0%, #c09c58 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  maxWidth: { xs: 100, sm: 180 },
                }}>
                  {conversationId ? "Conversation" : "New Chat"}
                </Typography>

                {/* Read-only active tier chip. TODO(P2-14): open the Dashboard's Tiers section. */}
                <TierChip tier={activeTier} onClick={() => router.push('/mission-control')} />

              </Box>
              
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                {isTTSEnabled && (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0, mr: 0.5 }}>
                    <Tooltip title={`Voice: ${ttsProvider === 'fishaudio' ? 'FishAudio (local)' : ttsProvider === 'qwen3' ? 'Qwen3-TTS (local)' : 'Edge-TTS (cloud)'}${ttsProvider !== 'edge' ? (ttsProvider === 'fishaudio' ? (fishaudioAvailable === null ? ' — Checking...' : fishaudioAvailable ? ' — Connected' : ' — Offline, will fallback to Edge') : (qwen3Available === null ? ' — Checking...' : qwen3Available ? ' — Connected' : ' — Offline, will fallback to Edge')) : ''}. Click to switch, right-click for voice menu.`}>
                      <Button
                        size="small"
                        onClick={() => handleProviderSwitch(ttsProvider === 'edge' ? 'qwen3' : ttsProvider === 'qwen3' ? 'fishaudio' : 'edge')}
                        onContextMenu={(e) => { e.preventDefault(); handleVoiceMenuOpen(e); }}
                        sx={{
                          minWidth: 0,
                          px: 1,
                          py: 0.25,
                          fontSize: '0.65rem',
                          fontWeight: 600,
                          fontFamily: 'monospace',
                          textTransform: 'none',
                          borderRadius: '6px',
                          color: ttsProvider === 'fishaudio' ? '#ff8c00' : ttsProvider === 'qwen3' ? '#c09c58' : 'rgba(255,255,255,0.6)',
                          border: '1px solid',
                          borderColor: ttsProvider === 'fishaudio' ? 'rgba(255,140,0,0.4)' : ttsProvider === 'qwen3' ? 'rgba(192,156,88,0.4)' : 'rgba(255,255,255,0.15)',
                          background: ttsProvider === 'fishaudio' ? 'rgba(255,140,0,0.1)' : ttsProvider === 'qwen3' ? 'rgba(192,156,88,0.1)' : 'transparent',
                          '&:hover': {
                            background: ttsProvider === 'fishaudio' ? 'rgba(255,140,0,0.2)' : ttsProvider === 'qwen3' ? 'rgba(192,156,88,0.2)' : 'rgba(255,255,255,0.08)',
                          },
                        }}
                      >
                        {ttsProvider === 'qwen3' && (
                          <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: qwen3Available === null ? '#ff9800' : qwen3Available ? '#4caf50' : '#f44336', mr: 0.5, flexShrink: 0 }} />
                        )}
                        {ttsProvider === 'fishaudio' && (
                          <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: fishaudioAvailable === null ? '#ff9800' : fishaudioAvailable ? '#4caf50' : '#f44336', mr: 0.5, flexShrink: 0 }} />
                        )}
                        {ttsProvider === 'fishaudio' ? 'FISH' : ttsProvider === 'qwen3' ? 'LOCAL' : 'EDGE'}
                      </Button>
                    </Tooltip>
                    <IconButton
                      onClick={handleVoiceMenuOpen}
                      size="small"
                      sx={{ p: 0.5, color: 'rgba(255,255,255,0.4)', '&:hover': { color: 'rgba(255,255,255,0.7)' } }}
                    >
                      <SettingsVoiceIcon sx={{ fontSize: 16 }} />
                    </IconButton>
                  </Box>
                )}
                <IconButton
                  onClick={toggleTTS}
                  color={isTTSEnabled ? "primary" : "default"}
                  size="small"
                  title={isTTSEnabled ? "Disable TTS" : "Enable TTS"}
                  sx={{
                    background: isTTSEnabled ? 'rgba(192,156,88,0.08)' : 'rgba(255,255,255,0.02)',
                    border: '1px solid',
                    borderColor: isTTSEnabled ? 'rgba(192,156,88,0.2)' : 'rgba(255,255,255,0.06)',
                    borderRadius: '8px',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    '&:hover': { background: isTTSEnabled ? 'rgba(192,156,88,0.15)' : 'rgba(255,255,255,0.06)' },
                  }}
                >
                  {isTTSEnabled ? <VolumeUpIcon /> : <VolumeOffIcon />}
                </IconButton>

                <IconButton
                  onClick={handleToggleDebugPanel}
                  color={isDebugPanelOpen ? "primary" : "default"}
                  size="small"
                  title="Toggle Debug Panel"
                  sx={{
                    background: isDebugPanelOpen ? 'rgba(192,156,88,0.08)' : 'rgba(255,255,255,0.02)',
                    border: '1px solid',
                    borderColor: isDebugPanelOpen ? 'rgba(192,156,88,0.2)' : 'rgba(255,255,255,0.06)',
                    borderRadius: '8px',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    '&:hover': { background: isDebugPanelOpen ? 'rgba(192,156,88,0.15)' : 'rgba(255,255,255,0.06)' },
                  }}
                >
                  <BugReportIcon />
                </IconButton>
                
                <IconButton
                  onClick={() => router.push('/mission-control')}
                  color="default"
                  size="small"
                  title="Mission Control"
                  sx={{
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.06)',
                    borderRadius: '8px',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    '&:hover': { background: 'rgba(255,255,255,0.06)' },
                  }}
                >
                  <TerminalIcon />
                </IconButton>

                <IconButton
                  onClick={() => router.push('/school')}
                  color="default"
                  size="small"
                  title="The Online School"
                  sx={{
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.06)',
                    borderRadius: '8px',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    '&:hover': { background: 'rgba(255,255,255,0.06)' },
                  }}
                >
                  <SchoolIcon />
                </IconButton>

                <IconButton
                  onClick={() => setGraphDialogOpen(true)}
                  color="default"
                  size="small"
                  title="Memory Graph"
                  sx={{
                    background: 'rgba(245,158,11,0.06)',
                    border: '1px solid rgba(245,158,11,0.15)',
                    borderRadius: '8px',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    '&:hover': { background: 'rgba(245,158,11,0.12)' },
                  }}
                >
                  <HubIcon sx={{ color: '#f59e0b' }} />
                </IconButton>

                <IconButton
                  onClick={() => router.push('/discord')}
                  color="default"
                  size="small"
                  title="Discord Bridge"
                  sx={{
                    background: 'rgba(88,101,242,0.06)',
                    border: '1px solid rgba(88,101,242,0.15)',
                    borderRadius: '8px',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    '&:hover': { background: 'rgba(88,101,242,0.12)' },
                  }}
                >
                  <DiscordIcon sx={{ color: '#7289da' }} />
                </IconButton>
              </Box>
            </Box>
            
            {/* Messages Area */}
            <Box sx={{ 
              flexGrow: 1, 
              p: { xs: 1, sm: 2 }, 
              overflow: 'auto',
              display: 'flex',
              flexDirection: 'column',
              height: 'calc(100vh - 138px)', // Subtract header and input area heights
              position: 'relative',
              '&:after': {
                content: '""',
                position: 'absolute',
                bottom: 0,
                left: 0,
                right: 0,
                height: '60px',
                background: 'linear-gradient(180deg, rgba(0, 0, 0, 0) 0%, rgba(0, 0, 0, 0.2) 100%)',
                pointerEvents: 'none',
                opacity: 0.7,
                zIndex: 1
              },
              '&:before': {
                content: '""',
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                height: '40px',
                background: 'linear-gradient(0deg, rgba(0, 0, 0, 0) 0%, rgba(0, 0, 0, 0.2) 100%)',
                pointerEvents: 'none',
                opacity: 0.7,
                zIndex: 1
              },
              scrollbarWidth: 'thin',
              scrollbarColor: 'rgba(255, 255, 255, 0.1) transparent',
              '&::-webkit-scrollbar': {
                width: '8px',
              },
              '&::-webkit-scrollbar-track': {
                background: 'transparent',
              },
              '&::-webkit-scrollbar-thumb': {
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
              },
              '&::-webkit-scrollbar-thumb:hover': {
                background: 'rgba(255, 255, 255, 0.2)',
              },
            }}>
              <Container 
                maxWidth="md" 
                sx={{ 
                  flexGrow: 1, 
                  py: 2,
                  zIndex: 2,
                  position: 'relative',
                }}
              >
                {!Array.isArray(messages) || messages.length === 0 ? (
                  conversationId && isLoading ? (
                    // Loading state
                    <Box sx={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      height: '100%'
                    }}>
                      <CircularProgress size={40} sx={{ mb: 2 }} />
                      <Typography variant="body1">Loading messages...</Typography>
                    </Box>
                  ) : null
                ) : (
                  // Messages list (all providers)
                  <>
                      {messages.map((message, index) => (
                        <ChatMessage
                          key={`${message.id}-${index}`}
                          message={message}
                          isLastMessage={index === messages.length - 1}
                          onViewChart={(config) => setChartDialogConfig(config)}
                        />
                      ))}
                      
                      {streamingResponse && (
                        <ChatMessage
                          message={{
                            id: 'streaming',
                            content: streamedContent,
                            role: 'assistant',
                            timestamp: new Date().toISOString(),
                            conversationId: conversationId || 'temp'
                          }}
                          isLastMessage={true}
                          onViewChart={(config) => setChartDialogConfig(config)}
                        />
                      )}
                      <div ref={messagesEndRef} />
                    </>
                  )}
              </Container>
            </Box>
            
            <Box sx={{ position: 'fixed', right: { xs: 16, md: 24 }, bottom: { xs: 96, md: 112 }, zIndex: 1320, pointerEvents: 'none' }}>
              {typeof process !== "undefined" && process.env.NEXT_PUBLIC_AVATAR_STAGE === "1" ? (
                <AvatarStage size={64} cognitiveState={avatarCognitiveState} />
              ) : (
                <SpiralAvatar size={64} />
              )}
            </Box>
            
            {/* Add this before the MessageInput component */}
            <ModelThinkingDisplay 
              visible={false && 
                (!!debugStreams.l1 || !!debugStreams.l2 || !!debugStreams.l3)}
              activeTabIndex={2} // Default to L3 (synthesis) tab
            />
            
            {/* Input Area - Fixed at bottom */}
            <Box sx={{
              p: 2,
              borderTop: '1px solid',
              borderColor: 'rgba(255, 255, 255, 0.06)',
              background: 'rgba(14, 14, 18, 0.72)',
              backdropFilter: 'blur(24px) saturate(180%)',
              WebkitBackdropFilter: 'blur(24px) saturate(180%)',
              boxShadow: '0 -4px 24px rgba(0, 0, 0, 0.2), inset 0 0 0 1px rgba(255,255,255,0.02)',
              borderRadius: '14px 14px 0 0',
              position: 'sticky',
              bottom: 0,
              left: 0,
              right: 0,
              width: '100%',
              zIndex: 1090
            }}>
              <Container maxWidth="md">
                <ChatInput 
                  onSendMessage={handleSendMessage}
                  isLoading={isLoading || streamingResponse}
                  disabled={!isConnected}
                  placeholder={isConnected ? "Ask Aura anything..." : "Connecting to server..."}
                />
              </Container>
            </Box>
          </Box>
          
          {/* Debug Panel Drawer - Enhanced with real-time stream data */}
          <Drawer
            variant="persistent"
            anchor="right"
            open={isDebugPanelOpen}
            sx={{
              width: isMobile ? '100%' : '350px', // Reduced from 400px to 350px
              flexShrink: 0,
              zIndex: 1400, // Increased from 1300 to 1400 to be above the left drawer
              display: 'block',
              position: 'fixed',
              right: 0,
              '& .MuiDrawer-paper': {
                width: isMobile ? '100%' : '350px',
                height: '100%',
                boxSizing: 'border-box',
                borderLeft: '1px solid',
                borderColor: 'rgba(255, 255, 255, 0.06)',
                background: 'rgba(14, 14, 18, 0.82)',
                backdropFilter: 'blur(24px) saturate(180%)',
                WebkitBackdropFilter: 'blur(24px) saturate(180%)',
                position: 'fixed',
                right: 0,
                top: 0,
                boxShadow: '-8px 0 32px rgba(0, 0, 0, 0.3), inset 0 0 0 1px rgba(255,255,255,0.02)',
                display: 'flex',
                flexDirection: 'column',
                overflowY: 'hidden',
              },
            }}
          >
            <Box sx={{
              p: 1.5,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
              flexShrink: 0,
              background: 'rgba(14,14,18,0.3)',
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
            }}>
              <Typography variant="subtitle1" sx={{ ml: 1 }}>Debug Panel</Typography>
              <IconButton 
                onClick={handleToggleDebugPanel}
                sx={{ 
                  "&:hover": { background: "rgba(255, 255, 255, 0.1)" },
                  zIndex: 1200
                }}
              >
                <CloseIcon />
              </IconButton>
            </Box>
            <Box sx={{ 
              flexGrow: 1, 
              overflowY: 'auto',
              overflowX: 'hidden' 
            }}>
              <DebugPanel conversationId={conversationId} />
            </Box>
          </Drawer>
        </Box>
        
        {/* Mobile Debug Panel Toggle - fix callback */}
        {isMobile && (
          <Fab
            color={isDebugPanelOpen ? "primary" : "default"}
            size="medium"
            aria-label="debug"
            onClick={handleToggleDebugPanel}
            sx={{
              position: 'fixed',
              bottom: 20,
              right: 20,
              display: isDebugPanelOpen ? 'none' : 'flex',
              zIndex: 2000,
              background: isDebugPanelOpen ? 'rgba(192,156,88,0.15)' : 'rgba(14,14,18,0.78)',
              backdropFilter: 'blur(16px) saturate(180%)',
              WebkitBackdropFilter: 'blur(16px) saturate(180%)',
              border: '1px solid rgba(255,255,255,0.08)',
              boxShadow: '0 8px 24px rgba(0, 0, 0, 0.3)',
              '&:hover': {
                background: isDebugPanelOpen ? 'rgba(192,156,88,0.22)' : 'rgba(24,24,30,0.78)',
              },
            }}
          >
            <BugReportIcon />
          </Fab>
        )}

        {/* Make sure mobile buttons are always visible even when panels are open */}
        {isMobile && (
          <Fab
            color={leftDrawerOpen ? "primary" : "default"}
            size="medium"
            aria-label="menu"
            onClick={toggleLeftDrawer}
            sx={{
              position: 'fixed',
              bottom: isDebugPanelOpen ? 80 : 20,
              left: 20,
              zIndex: 2000,
              background: leftDrawerOpen ? 'rgba(192,156,88,0.15)' : 'rgba(14,14,18,0.78)',
              backdropFilter: 'blur(16px) saturate(180%)',
              WebkitBackdropFilter: 'blur(16px) saturate(180%)',
              border: '1px solid rgba(255,255,255,0.08)',
              boxShadow: '0 8px 24px rgba(0, 0, 0, 0.3)',
              display: 'flex',
              '&:hover': {
                background: leftDrawerOpen ? 'rgba(192,156,88,0.22)' : 'rgba(24,24,30,0.78)',
              },
            }}
          >
            <MenuIcon />
          </Fab>
        )}
        
        {/* Goal Pursuit Modal */}
        <GoalPursuitModal
          open={goalPursuitModal.open}
          goal={goalPursuitModal.goal}
          onClose={() => setGoalPursuitModal({ open: false, goal: null })}
          onConfirm={handleGoalPursuitConfirm}
        />

        {/* System Restart Modal (self-modification safety) */}
        <SystemRestartModal
          open={restartModalOpen}
          modifiedPath={restartModifiedPath}
          onClose={() => setRestartModalOpen(false)}
          onRestart={async () => {
            try {
              await auraApi.restartSystem();
            } catch (e) {
              console.error('Failed to trigger restart:', e);
            } finally {
              setRestartModalOpen(false);
            }
          }}
        />

        {/* Chart.js Dialog — renders chart in a popup window */}
        <ChartDialog
          config={chartDialogConfig}
          open={chartDialogConfig !== null}
          onClose={() => setChartDialogConfig(null)}
        />

        {/* Memory Graph Dialog — D3 force graph popup */}
        <MemoryGraphDialog
          open={graphDialogOpen}
          onClose={() => setGraphDialogOpen(false)}
        />

        {/* Cognitive Telemetry — mounts WebSocket only when open */}
        <CognitiveTelemetry
          open={telemetryOpen}
          onClose={() => setTelemetryOpen(false)}
        />
      </Box>
    </ParticlesBackground>
  );
} 
