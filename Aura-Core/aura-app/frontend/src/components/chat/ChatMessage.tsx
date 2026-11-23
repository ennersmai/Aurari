import React from 'react';
import { Box, Typography, Avatar, Paper, Chip } from '@mui/material';
import { formatDistanceToNow } from 'date-fns';
import { ChatMessage as ChatMessageType } from '@/services/socketService';
import MarkdownRenderer from './MarkdownRenderer';
import PersonIcon from '@mui/icons-material/Person';
import SpiralAvatar from '@/components/SpiralAvatar';
import type { ChartJsConfig } from './ChartRenderer';
import { DeepReasoningMarker } from './TurnMarkers';

interface ChatMessageProps {
  message: ChatMessageType;
  isLastMessage?: boolean;
  onViewChart?: (config: ChartJsConfig) => void;
}

export default function ChatMessage({ message, isLastMessage = false, onViewChart }: ChatMessageProps) {
  const { role, content, timestamp } = message;
  const isUser = role === 'user';
  
  const formattedTime = timestamp 
    ? formatDistanceToNow(new Date(timestamp), { addSuffix: true })
    : '';
  
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'row',
        mb: 3,
        alignItems: 'flex-start',
        maxWidth: '100%'
      }}
    >
      <Avatar
        sx={{
          bgcolor: isUser ? 'rgba(24, 24, 30, 0.7)' : 'rgba(12, 12, 18, 0.85)',
          mr: 2,
          mt: 0.5,
          border: isUser
            ? '1px solid rgba(255, 255, 255, 0.08)'
            : '1px solid rgba(192, 156, 88, 0.4)',
          backdropFilter: 'blur(16px) saturate(180%)',
          WebkitBackdropFilter: 'blur(16px) saturate(180%)',
          boxShadow: isUser
            ? '0 2px 12px rgba(0, 0, 0, 0.15)'
            : '0 0 22px rgba(192, 156, 88, 0.25), inset 0 0 12px rgba(192,156,88,0.15)',
          width: 42,
          height: 42,
          overflow: 'hidden',
          padding: '2px',
        }}
      >
        {isUser ? <PersonIcon sx={{ fontSize: 26 }} /> : <SpiralAvatar size={34} />}
      </Avatar>
      
      <Box sx={{ maxWidth: 'calc(100% - 60px)' }}>
        <Box 
          sx={{ 
            display: 'flex', 
            alignItems: 'center', 
            mb: 0.5 
          }}
        >
          <Typography 
            variant="subtitle1" 
            fontWeight="600" 
            mr={1}
            sx={{
              color: isUser ? 'rgba(255,255,255,0.9)' : 'rgba(192, 156, 88, 0.9)',
              fontSize: '0.85rem',
            }}
          >
            {isUser ? 'You' : 'Aura'}
          </Typography>
          <Typography 
            variant="caption" 
            color="text.secondary"
            sx={{ opacity: 0.5, fontSize: '0.65rem' }}
          >
            {formattedTime}
          </Typography>
          {!isUser && <DeepReasoningMarker meta={message.turnMeta} />}
        </Box>
        
        <Paper
          elevation={0}
          sx={{
            p: 2,
            borderRadius: isUser ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
            backgroundColor: isUser 
              ? 'rgba(40, 40, 48, 0.55)' 
              : 'rgba(24, 24, 30, 0.6)',
            backdropFilter: 'blur(16px) saturate(160%)',
            WebkitBackdropFilter: 'blur(16px) saturate(160%)',
            border: '1px solid',
            borderColor: isUser 
              ? 'rgba(255, 255, 255, 0.06)' 
              : 'rgba(192, 156, 88, 0.08)',
            boxShadow: isUser 
              ? '0 4px 16px rgba(0, 0, 0, 0.1)' 
              : '0 4px 20px rgba(0, 0, 0, 0.12)',
            maxWidth: '100%',
            overflowX: 'auto',
            position: 'relative',
            '&::before': isUser ? undefined : {
              content: '""',
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              height: '1px',
              background: 'linear-gradient(90deg, rgba(192, 156, 88, 0), rgba(192, 156, 88, 0.12), rgba(192, 156, 88, 0))',
              borderRadius: 'inherit',
            },
            '&::after': {
              content: '""',
              position: 'absolute',
              inset: 0,
              borderRadius: 'inherit',
              background: isUser
                ? 'linear-gradient(135deg, rgba(255,255,255,0.03) 0%, transparent 60%)'
                : 'linear-gradient(135deg, rgba(192,156,88,0.03) 0%, transparent 60%)',
              pointerEvents: 'none',
            },
          }}
        >
          <MarkdownRenderer content={content} onViewChart={onViewChart} />
        </Paper>
        
        {isLastMessage && isUser && (
          <Chip 
            size="small"
            label="Seen" 
            sx={{ 
              mt: 1, 
              height: 20, 
              fontSize: '0.55rem',
              background: 'rgba(192, 156, 88, 0.1)',
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
              color: 'rgba(192, 156, 88, 0.8)',
              border: '1px solid rgba(192, 156, 88, 0.15)',
              borderRadius: '8px',
            }}
          />
        )}
      </Box>
    </Box>
  );
}
