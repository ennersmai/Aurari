import React, { memo, useState, useRef, useEffect, useCallback } from 'react';
import { Box, IconButton, Tooltip } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import CloseFullscreenIcon from '@mui/icons-material/CloseFullscreen';
import WallpaperIcon from '@mui/icons-material/Wallpaper';
import ImageNotSupportedIcon from '@mui/icons-material/ImageNotSupported';
import MinimizeIcon from '@mui/icons-material/Minimize';
import SpiralAvatar from '@/components/SpiralAvatar';
import AuraAvatar from '@/components/AuraAvatar';

/**
 * FloatingAvatarWindow
 *
 * Renders AuraAvatar inside a resizable, draggable popup anchored to the
 * bottom-right of the viewport.
 *
 * ## Modes
 *
 * **Windowed (default)**: Small floating window, draggable + resizable.
 * **Fullscreen**: Covers the entire viewport. A top-right control bar
 *   lets the user return to windowed mode, upload a background, or minimise.
 *
 * ## Mount / Unmount Behaviour
 *
 * `<AuraAvatar />` is rendered in a SINGLE place in the JSX tree (not inside
 * conditional branches), so toggling between windowed and fullscreen does NOT
 * cause a remount. Only the wrapper CSS changes.
 *
 * When the user hides the window (X / Minimise), `isOpen` becomes false and
 * the entire subtree unmounts, releasing the WebGL context as intended.
 *
 * ## 3-D Camera Controls (zoom / pan / tilt)
 *
 * The Three.js OrbitControls are already wired to `renderer.domElement` inside
 * `viewer.ts`. Mouse events on the canvas are consumed by OrbitControls:
 *   • Left-drag  → orbit / tilt
 *   • Right-drag → pan
 *   • Scroll     → zoom
 *
 * The parent drag-to-move handler explicitly excludes `<canvas>` targets, so
 * OrbitControls and window dragging never conflict.
 */

/** Accepted background image MIME types. */
const BG_ACCEPT = '.jpg,.jpeg,.png,.webp';

function FloatingAvatarWindow() {
  // ── Visibility / mode ────────────────────────────────────────────────────
  const [isOpen, setIsOpen] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // ── Background image (data-URL) ──────────────────────────────────────────
  const [backgroundImage, setBackgroundImage] = useState<string | null>(null);
  const bgInputRef = useRef<HTMLInputElement>(null);

  // ── Windowed drag state ───────────────────────────────────────────────────
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const windowRef = useRef<HTMLDivElement>(null);
  const dragStartRef = useRef({ x: 0, y: 0, left: 0, top: 0 });

  // ── Background image upload ───────────────────────────────────────────────
  const handleBgUpload = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => setBackgroundImage(ev.target?.result as string);
      reader.readAsDataURL(file);
      // Reset so re-uploading the same file fires onChange again
      e.target.value = '';
    },
    [],
  );

  // ── Window drag handlers (windowed mode only) ─────────────────────────────
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (isFullscreen) return;
      if (!windowRef.current) return;

      const target = e.target as HTMLElement;
      // Do NOT start a window-drag if the click was on:
      //   • any button (so icon buttons keep their own click handlers)
      //   • a <canvas> tag (so OrbitControls receive the event undisturbed)
      //   • a resize handle
      if (
        target.closest('button') ||
        target.tagName === 'CANVAS' ||
        target.closest('[data-no-drag]')
      ) {
        return;
      }

      const rect = windowRef.current.getBoundingClientRect();
      setIsDragging(true);
      dragStartRef.current = {
        x: e.clientX,
        y: e.clientY,
        left: rect.left,
        top: rect.top,
      };

      document.body.style.cursor = 'grabbing';
      document.body.style.userSelect = 'none';
    },
    [isFullscreen],
  );

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!isDragging || !windowRef.current) return;

      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;

      const newLeft = Math.max(
        10,
        Math.min(window.innerWidth - 300, dragStartRef.current.left + dx),
      );
      const newTop = Math.max(
        10,
        Math.min(window.innerHeight - 250, dragStartRef.current.top + dy),
      );

      setPosition({ x: newLeft, y: newTop });
    },
    [isDragging],
  );

  const handleMouseUp = useCallback(() => {
    if (isDragging) {
      setIsDragging(false);
      document.body.style.cursor = 'default';
      document.body.style.userSelect = 'auto';
    }
  }, [isDragging]);

  useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  // ── Reset drag position when leaving fullscreen back to windowed ──────────
  const handleExitFullscreen = useCallback(() => {
    setIsFullscreen(false);
  }, []);

  // ─────────────────────────────────────────────────────────────────────────
  // HIDDEN STATE – show just the spiral FAB button
  // ─────────────────────────────────────────────────────────────────────────
  if (!isOpen) {
    return (
      <Tooltip title="Show Aura Avatar">
        <IconButton
          onClick={() => setIsOpen(true)}
          sx={{
            position: 'fixed',
            right: { xs: 16, md: 24 },
            bottom: { xs: 96, md: 112 },
            zIndex: 1320,
            width: 48,
            height: 48,
            color: 'rgba(245, 204, 127, 0.95)',
            background: 'rgba(18, 18, 22, 0.88)',
            border: '1px solid rgba(245, 204, 127, 0.25)',
            backdropFilter: 'blur(15px)',
            boxShadow: '0 10px 30px rgba(0, 0, 0, 0.45)',
            '&:hover': { background: 'rgba(245, 204, 127, 0.12)' },
          }}
        >
          <SpiralAvatar size={32} />
        </IconButton>
      </Tooltip>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Shared background-image CSS (applied to content layer in both modes)
  // ─────────────────────────────────────────────────────────────────────────
  const bgStyles = backgroundImage
    ? {
        backgroundImage: `url(${backgroundImage})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundRepeat: 'no-repeat',
      }
    : {};

  // ─────────────────────────────────────────────────────────────────────────
  // Shared toolbar – rendered identically in both modes
  // ─────────────────────────────────────────────────────────────────────────
  const toolbar = (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.25,
        px: 0.75,
        py: 0.5,
        background: 'rgba(8, 8, 12, 0.72)',
        backdropFilter: 'blur(14px)',
        borderBottom: isFullscreen
          ? 'none'
          : '1px solid rgba(255, 255, 255, 0.06)',
        borderRadius: isFullscreen ? 2 : 0,
        border: isFullscreen
          ? '1px solid rgba(245, 204, 127, 0.22)'
          : undefined,
        flexShrink: 0,
        userSelect: 'none',
        cursor: isFullscreen ? 'default' : 'grab',
      }}
    >
      {/* Drag hint (windowed only) */}
      {!isFullscreen && (
        <Tooltip title="Drag window to move · Resize from bottom-right corner">
          <OpenInFullIcon
            sx={{
              fontSize: 13,
              color: 'rgba(245, 204, 127, 0.45)',
              transform: 'rotate(45deg)',
              mr: 0.25,
            }}
          />
        </Tooltip>
      )}

      {/* Upload / change background */}
      <Tooltip title="Upload background image (PNG / JPG / WebP)">
        <IconButton
          size="small"
          onClick={() => bgInputRef.current?.click()}
          sx={{
            color: backgroundImage
              ? '#f5cc7f'
              : 'rgba(255,255,255,0.5)',
            '&:hover': {
              color: '#f5cc7f',
              background: 'rgba(245,204,127,0.12)',
            },
          }}
        >
          <WallpaperIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Tooltip>

      {/* Remove background (only visible when a bg is set) */}
      {backgroundImage && (
        <Tooltip title="Remove background image">
          <IconButton
            size="small"
            onClick={() => setBackgroundImage(null)}
            sx={{
              color: 'rgba(255,100,100,0.7)',
              '&:hover': {
                color: '#ff6464',
                background: 'rgba(255,80,80,0.12)',
              },
            }}
          >
            <ImageNotSupportedIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      )}

      {/* Fullscreen / exit-fullscreen toggle */}
      {isFullscreen ? (
        <Tooltip title="Return to windowed mode">
          <IconButton
            size="small"
            onClick={handleExitFullscreen}
            sx={{
              color: 'rgba(255,255,255,0.65)',
              '&:hover': {
                color: '#f5cc7f',
                background: 'rgba(245,204,127,0.12)',
              },
            }}
          >
            <CloseFullscreenIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      ) : (
        <Tooltip title="Expand to fullscreen (background mode)">
          <IconButton
            size="small"
            onClick={() => setIsFullscreen(true)}
            sx={{
              color: 'rgba(255,255,255,0.65)',
              '&:hover': {
                color: '#f5cc7f',
                background: 'rgba(245,204,127,0.12)',
              },
            }}
          >
            <OpenInFullIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      )}

      {/* Minimise / hide */}
      <Tooltip title={isFullscreen ? 'Minimise avatar' : 'Hide avatar'}>
        <IconButton
          size="small"
          onClick={() => {
            setIsFullscreen(false);
            setIsOpen(false);
          }}
          sx={{
            color: 'rgba(255,255,255,0.55)',
            '&:hover': {
              color: '#ff6464',
              background: 'rgba(255,80,80,0.12)',
            },
          }}
        >
          {isFullscreen ? (
            <MinimizeIcon sx={{ fontSize: 16 }} />
          ) : (
            <CloseIcon sx={{ fontSize: 16 }} />
          )}
        </IconButton>
      </Tooltip>
    </Box>
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Main render – single AuraAvatar instance; only container CSS changes
  // between windowed and fullscreen to prevent remounting the WebGL context.
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <>
      {/* Hidden file input for background upload */}
      <input
        ref={bgInputRef}
        type="file"
        accept={BG_ACCEPT}
        style={{ display: 'none' }}
        onChange={handleBgUpload}
      />

      <Box
        ref={windowRef}
        onMouseDown={handleMouseDown}
        sx={
          isFullscreen
            ? /* ── FULLSCREEN ──────────────────────────────────────── */
              {
                position: 'fixed',
                inset: 0,
                zIndex: 9990,
                width: '100vw',
                height: '100vh',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
                // Background image fills the whole screen
                ...bgStyles,
                backgroundColor: backgroundImage
                  ? 'transparent'
                  : 'rgba(6, 6, 10, 0.98)',
              }
            : /* ── WINDOWED ────────────────────────────────────────── */
              {
                position: 'fixed',
                left: position.x || { xs: 12, md: 24 },
                top: position.y || { xs: 'auto', md: 'auto' },
                bottom: position.y ? 'auto' : { xs: 92, md: 112 },
                right: position.x ? 'auto' : { xs: 12, md: 24 },
                zIndex: 1310,
                width: { xs: 'min(92vw, 360px)', md: 380 },
                height: { xs: 300, md: 420 },
                minWidth: 260,
                minHeight: 240,
                maxWidth: 'calc(100vw - 32px)',
                maxHeight: 'calc(100vh - 150px)',
                resize: 'both',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                borderRadius: 3,
                border: '1px solid rgba(245, 204, 127, 0.35)',
                backdropFilter: backgroundImage
                  ? 'none'
                  : 'blur(22px) saturate(180%)',
                boxShadow:
                  '0 22px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(245,204,127,0.15)',
                cursor: isDragging ? 'grabbing' : 'grab',
                transition: isDragging
                  ? 'none'
                  : 'box-shadow 0.2s ease, border-color 0.2s ease',
                '&:hover': {
                  boxShadow:
                    '0 26px 70px rgba(0,0,0,0.65), 0 0 0 1px rgba(245,204,127,0.3)',
                  borderColor: 'rgba(245, 204, 127, 0.45)',
                },
                '&:active': { cursor: 'grabbing' },
                // Background image fills the windowed frame
                ...bgStyles,
                backgroundColor: backgroundImage
                  ? 'transparent'
                  : 'rgba(8, 8, 12, 0.92)',
              }
        }
      >
        {/* ── Top control bar ────────────────────────────────────────────── */}
        {isFullscreen ? (
          /* In fullscreen: bar floats top-right via absolute positioning */
          <Box
            sx={{
              position: 'absolute',
              top: 14,
              right: 18,
              zIndex: 10,
              // The toolbar itself handles its own border / backdrop
            }}
          >
            {toolbar}
          </Box>
        ) : (
          /* In windowed: bar is a flex row header at the top */
          <Box
            sx={{
              height: 36,
              px: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              flexShrink: 0,
            }}
          >
            {toolbar}
          </Box>
        )}

        {/* ── VRM canvas area ────────────────────────────────────────────── */}
        {/*
          `pointer-events: auto` on the canvas container ensures OrbitControls
          (attached to renderer.domElement) receive all mouse events for:
            • left-drag  → orbit / tilt
            • right-drag → pan
            • scroll     → zoom in / out
          The parent onMouseDown handler excludes <canvas> tags (see top of
          component), so window-dragging and orbit-controls never conflict.
        */}
        <Box
          sx={{
            position: 'relative',
            flexGrow: 1,
            overflow: 'hidden',
            // Transparent so background image (on parent) shows through
            background: 'transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            // Ensure canvas captures pointer events for OrbitControls
            '& canvas': { pointerEvents: 'auto', cursor: 'grab' },
            '& canvas:active': { cursor: 'grabbing' },
          }}
        >
          <AuraAvatar />
        </Box>

        {/* ── Subtle golden accent bar at the very bottom ────────────────── */}
        <Box
          sx={{
            height: 3,
            flexShrink: 0,
            background:
              'linear-gradient(90deg, transparent, rgba(192,156,88,0.55), transparent)',
            pointerEvents: 'none',
          }}
        />
      </Box>
    </>
  );
}

export default memo(FloatingAvatarWindow);
