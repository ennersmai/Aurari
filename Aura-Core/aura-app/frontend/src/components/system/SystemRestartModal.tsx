import React from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
} from '@mui/material';

interface SystemRestartModalProps {
  open: boolean;
  modifiedPath: string | null;
  onClose: () => void;
  onRestart: () => Promise<void> | void;
}

export default function SystemRestartModal(props: SystemRestartModalProps) {
  const { open, modifiedPath, onClose, onRestart } = props;
  const [isRestarting, setIsRestarting] = React.useState(false);

  const handleRestart = async () => {
    try {
      setIsRestarting(true);
      await onRestart();
    } finally {
      setIsRestarting(false);
    }
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      PaperProps={{
        sx: {
          background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)',
          border: '1px solid rgba(139, 92, 246, 0.3)',
        },
      }}
    >
      <DialogTitle
        sx={{
          color: '#e0e0e0',
          borderBottom: '1px solid rgba(139, 92, 246, 0.2)',
          fontFamily: 'monospace',
        }}
      >
        🩺 System Patch Applied
      </DialogTitle>
      <DialogContent sx={{ mt: 2 }}>
        <Typography variant="body1" sx={{ color: '#e0e0e0', mb: 2 }}>
          Aura just modified part of her own brain (core backend code).
        </Typography>
        {modifiedPath && (
          <Box
            sx={{
              mb: 2,
              p: 1.5,
              borderRadius: 1,
              backgroundColor: 'rgba(139, 92, 246, 0.1)',
              border: '1px solid rgba(139, 92, 246, 0.4)',
              fontFamily: 'monospace',
              fontSize: '0.85rem',
              color: '#c4c4ff',
              wordBreak: 'break-all',
            }}
          >
            {modifiedPath}
          </Box>
        )}
        <Typography variant="body2" sx={{ color: '#b0b0b0', mb: 1 }}>
          To make this change take effect, you need to restart the backend container.
        </Typography>
        <Typography variant="body2" sx={{ color: '#9e9e9e' }}>
          After restart, Aura will boot with the new behavior.
        </Typography>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
          <Button
            onClick={onClose}
            disabled={isRestarting}
            sx={{ textTransform: 'none' }}
          >
            Later
          </Button>
          <Button
            onClick={handleRestart}
            disabled={isRestarting}
            variant="contained"
            sx={{
              background: 'linear-gradient(90deg, #8b5cf6 0%, #6366f1 100%)',
              textTransform: 'none',
              fontWeight: 600,
            }}
          >
            {isRestarting ? 'Restarting…' : 'Restart Now'}
          </Button>
        </Box>
      </DialogActions>
    </Dialog>
  );
}


