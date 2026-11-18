import React, { useState, useMemo } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  IconButton,
  Box,
  Typography,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import BarChartIcon from '@mui/icons-material/BarChart';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  ArcElement,
  RadialLinearScale,
  RadarController,
  PolarAreaController,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Bar, Line, Pie, Doughnut, Radar, PolarArea, Bubble, Scatter } from 'react-chartjs-2';

// ---------------------------------------------------------------------------
// Register Chart.js components once
// ---------------------------------------------------------------------------
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  ArcElement,
  RadialLinearScale,
  RadarController,
  PolarAreaController,
  Title,
  Tooltip,
  Legend,
  Filler
);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface ChartJsConfig {
  type: 'bar' | 'line' | 'pie' | 'doughnut' | 'radar' | 'polarArea' | 'bubble' | 'scatter';
  data: {
    labels: string[];
    datasets: Array<{
      label: string;
      data: number[];
      backgroundColor?: string | string[];
      borderColor?: string | string[];
      borderWidth?: number;
      fill?: boolean;
      tension?: number;
    }>;
  };
  options?: Record<string, unknown>;
}

interface ChartRendererProps {
  config: ChartJsConfig;
}

// ---------------------------------------------------------------------------
// Chart type → Component mapping
// ---------------------------------------------------------------------------
const chartComponentMap: Record<string, React.ComponentType<any>> = {
  bar: Bar,
  line: Line,
  pie: Pie,
  doughnut: Doughnut,
  radar: Radar,
  polarArea: PolarArea,
  bubble: Bubble,
  scatter: Scatter,
};

// ---------------------------------------------------------------------------
// Dark-theme defaults merged into chart options
// ---------------------------------------------------------------------------
function applyDarkTheme(options: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...options,
    responsive: true,
    maintainAspectRatio: true,
    plugins: {
      ...(options.plugins as object || {}),
      legend: {
        position: 'top' as const,
        labels: {
          color: 'rgba(255, 255, 255, 0.75)',
          font: { size: 12 },
          ...((options.plugins as any)?.legend?.labels || {}),
        },
        ...((options.plugins as any)?.legend || {}),
      },
      title: {
        display: true,
        color: 'rgba(255, 255, 255, 0.85)',
        font: { size: 16, weight: 'bold' as const },
        ...((options.plugins as any)?.title || {}),
      },
    },
    scales: !['pie', 'doughnut', 'polarArea', 'radar'].includes(
      (options as any)?.type || ''
    )
      ? {
          x: {
            ticks: { color: 'rgba(255, 255, 255, 0.6)' },
            grid: { color: 'rgba(255, 255, 255, 0.06)' },
            ...((options as any)?.scales?.x || {}),
          },
          y: {
            ticks: { color: 'rgba(255, 255, 255, 0.6)' },
            grid: { color: 'rgba(255, 255, 255, 0.06)' },
            beginAtZero: true,
            ...((options as any)?.scales?.y || {}),
          },
        }
      : (options as any)?.scales || undefined,
  };
}

// ---------------------------------------------------------------------------
// ChartRenderer — renders a single Chart.js chart (used inside the dialog)
// ---------------------------------------------------------------------------
function ChartCanvas({ config }: ChartRendererProps) {
  const theme = useTheme();

  const mergedOptions = useMemo(
    () => applyDarkTheme({ ...config.options, type: config.type }),
    [config.options, config.type]
  );

  const chartData = useMemo(
    () => ({
      labels: config.data.labels,
      datasets: config.data.datasets.map((ds) => ({
        ...ds,
        backgroundColor: ds.backgroundColor || 'rgba(59, 130, 246, 0.7)',
        borderColor: ds.borderColor || 'rgba(59, 130, 246, 1)',
        borderWidth: ds.borderWidth ?? 1,
      })),
    }),
    [config.data]
  );

  const ChartComponent = chartComponentMap[config.type];
  if (!ChartComponent) {
    return (
      <Typography color="error">
        Unsupported chart type: {config.type}
      </Typography>
    );
  }

  return (
    <Box
      sx={{
        width: '100%',
        height: '100%',
        minHeight: 280,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        p: 1,
      }}
    >
      <ChartComponent data={chartData} options={mergedOptions} />
    </Box>
  );
}

// ---------------------------------------------------------------------------
// ChartDialog — full pop-up dialog wrapping ChartCanvas
// ---------------------------------------------------------------------------
export default function ChartDialog({
  config,
  open,
  onClose,
}: {
  config: ChartJsConfig | null;
  open: boolean;
  onClose: () => void;
}) {
  const [fullscreen, setFullscreen] = useState(false);

  if (!config) return null;

  const title =
    (config.options?.plugins as any)?.title?.text ||
    `${config.type.charAt(0).toUpperCase() + config.type.slice(1)} Chart`;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullScreen={fullscreen}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          background:
            'linear-gradient(145deg, rgba(18, 18, 24, 0.96) 0%, rgba(24, 24, 32, 0.96) 100%)',
          backdropFilter: 'blur(24px) saturate(180%)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: fullscreen ? 0 : '18px',
          boxShadow: '0 24px 64px rgba(0, 0, 0, 0.45)',
          overflow: 'hidden',
          minHeight: fullscreen ? '100vh' : 420,
        },
      }}
    >
      <DialogTitle
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 3,
          py: 1.5,
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          background: 'rgba(255,255,255,0.015)',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2 }}>
          <BarChartIcon sx={{ color: '#c09c58', fontSize: 22 }} />
          <Typography
            variant="h6"
            sx={{
              fontWeight: 600,
              fontSize: '1rem',
              background: 'linear-gradient(90deg, #f5cc7f 0%, #c09c58 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            {title}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <IconButton
            size="small"
            onClick={() => setFullscreen((f) => !f)}
            sx={{ color: 'rgba(255,255,255,0.5)' }}
          >
            {fullscreen ? <FullscreenExitIcon /> : <FullscreenIcon />}
          </IconButton>
          <IconButton size="small" onClick={onClose} sx={{ color: 'rgba(255,255,255,0.5)' }}>
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>

      <DialogContent
        sx={{
          px: 3,
          py: 2,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: fullscreen ? 'calc(100vh - 120px)' : 360,
        }}
      >
        <ChartCanvas config={config} />
      </DialogContent>

      <DialogActions
        sx={{
          px: 3,
          py: 1.5,
          borderTop: '1px solid rgba(255,255,255,0.06)',
          background: 'rgba(255,255,255,0.01)',
        }}
      >
        <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.35)', mr: 'auto' }}>
          {config.type} · {config.data.labels.length} data points
        </Typography>
        <Button onClick={onClose} sx={{ color: '#c09c58', textTransform: 'none' }}>
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Helper: parse [CHARTJS:<base64>] markers from message text
// ---------------------------------------------------------------------------
export function extractChartConfigs(
  content: string
): { cleanContent: string; charts: ChartJsConfig[] } {
  const charts: ChartJsConfig[] = [];
  const markerRegex = /\[CHARTJS:([A-Za-z0-9+/=]+)\]/g;

  const cleanContent = content.replace(markerRegex, (match, b64: string) => {
    try {
      const decoded = atob(b64);
      const config = JSON.parse(decoded) as ChartJsConfig;
      charts.push(config);
      // Replace with a short label that will be detected in MarkdownRenderer
      const title =
        (config.options?.plugins as any)?.title?.text ||
        `${config.type.charAt(0).toUpperCase() + config.type.slice(1)} Chart`;
      return `📊 **${title}**  \n`;
    } catch {
      // If decoding fails, leave the marker unchanged
      return match;
    }
  });

  return { cleanContent, charts };
}
