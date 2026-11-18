import React, { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { Box, Typography, Link, Button, Chip } from '@mui/material';
import BarChartIcon from '@mui/icons-material/BarChart';
import { extractChartConfigs, type ChartJsConfig } from './ChartRenderer';

interface MarkdownRendererProps {
  content: string;
  onViewChart?: (config: ChartJsConfig) => void;
}

// Using a more compatible type definition for ReactMarkdown components
type ComponentPropsType = React.DetailedHTMLProps<
  React.HTMLAttributes<HTMLElement>, 
  HTMLElement
> & { 
  node?: unknown; 
  inline?: boolean;
  className?: string;
  children?: React.ReactNode;
};

export default function MarkdownRenderer({ content, onViewChart }: MarkdownRendererProps) {

  // Extract [CHARTJS:...] markers and produce clean markdown + chart configs
  const { cleanContent, charts } = useMemo(
    () => extractChartConfigs(content),
    [content]
  );

  // Build a "View Chart" button for each extracted chart
  const chartButtons = useMemo(() => {
    if (!charts.length || !onViewChart) return null;
    return (
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 1.5 }}>
        {charts.map((cfg, idx) => {
          const title =
            (cfg.options?.plugins as any)?.title?.text ||
            `${cfg.type.charAt(0).toUpperCase() + cfg.type.slice(1)} Chart`;
          return (
            <Button
              key={idx}
              size="small"
              variant="outlined"
              startIcon={<BarChartIcon />}
              onClick={() => onViewChart(cfg)}
              sx={{
                textTransform: 'none',
                fontSize: '0.78rem',
                borderColor: 'rgba(192, 156, 88, 0.35)',
                color: '#c09c58',
                borderRadius: '10px',
                px: 2,
                '&:hover': {
                  borderColor: 'rgba(192, 156, 88, 0.6)',
                  background: 'rgba(192, 156, 88, 0.08)',
                },
              }}
            >
              {title}
            </Button>
          );
        })}
      </Box>
    );
  }, [charts, onViewChart]);
  return (
    <Box sx={{ 
      '& pre': { 
        borderRadius: 1,
        p: 2,
        overflowX: 'auto',
        backgroundColor: 'rgba(0, 0, 0, 0.04)',
      },
      '& code': {
        fontFamily: 'monospace',
        p: 0.5,
        borderRadius: 0.5,
        backgroundColor: 'rgba(0, 0, 0, 0.04)',
      },
      '& pre > code': {
        p: 0,
        backgroundColor: 'transparent',
      },
      '& blockquote': {
        borderLeft: '4px solid',
        borderColor: 'divider',
        pl: 2,
        ml: 0,
        my: 2,
      },
      '& img': {
        maxWidth: '100%',
        height: 'auto',
      },
      '& table': {
        borderCollapse: 'collapse',
        width: '100%',
        my: 2,
      },
      '& th, & td': {
        border: '1px solid',
        borderColor: 'divider',
        p: 1,
      },
      '& th': {
        backgroundColor: 'rgba(0, 0, 0, 0.04)',
        fontWeight: 'bold',
      }
    }}>
      {/* "View Chart" buttons rendered above markdown content */}
      {chartButtons}

      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          h1: (props) => <Typography variant="h4" gutterBottom {...props} />,
          h2: (props) => <Typography variant="h5" gutterBottom {...props} />,
          h3: (props) => <Typography variant="h6" gutterBottom {...props} />,
          h4: (props) => <Typography variant="subtitle1" gutterBottom {...props} />,
          h5: (props) => <Typography variant="subtitle2" gutterBottom {...props} />,
          h6: (props) => <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }} gutterBottom {...props} />,
          p: (props) => <Typography variant="body1" component="div" paragraph {...props} />,
          a: (props) => <Link color="primary" {...props} />,
          code: ({ inline, className, children, ...rest }: ComponentPropsType) => {
            if (inline) {
              return (
                <code className={className} {...rest}>
                  {children}
                </code>
              );
            }
            
            return (
              <pre className={className}>
                <code {...rest}>{children}</code>
              </pre>
            );
          }
        }}
      >
        {cleanContent}
      </ReactMarkdown>
    </Box>
  );
} 