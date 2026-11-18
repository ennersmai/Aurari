"use client";

import { memo, useContext, useState, useRef, useEffect, useCallback } from "react";
import { Box, IconButton, Menu, MenuItem, Typography, Tooltip } from "@mui/material";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import { ViewerContext } from "./vrm-engine/features/vrmViewer/viewerContext";
import { useVrmStoreContext } from "./vrm-engine/features/vrmStore/vrmStoreContext";
import { getVrmDisplayName } from "./vrm-engine/paths";

/**
 * VrmModelSelector
 *
 * Compact dropdown for switching between available VRM avatar models.
 * Displays the current model name and provides a menu to select any
 * available model from the vrmStore.
 *
 * Usage:
 *   <VrmModelSelector />
 *
 * Requires:
 *   - VrmStoreProvider ancestor (provided by AuraAvatar)
 *   - ViewerContext ancestor (provided by AuraAvatar)
 */
function VrmModelSelector() {
  const { viewer } = useContext(ViewerContext);
  const { vrmList, getCurrentVrm, selectVrm } = useVrmStoreContext();

  const currentVrm = getCurrentVrm();
  const currentName = currentVrm
    ? getVrmDisplayName(currentVrm.url)
    : "Select Model";

  const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null);
  const menuOpen = Boolean(menuAnchor);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const handleOpen = useCallback(() => {
    setMenuAnchor(buttonRef.current);
  }, []);

  const handleClose = useCallback(() => {
    setMenuAnchor(null);
  }, []);

  const handleSelect = useCallback(
    (index: number) => {
      const vrm = vrmList[index];
      if (!vrm) return;
      selectVrm(vrm, viewer);
      handleClose();
    },
    [vrmList, viewer, selectVrm, handleClose],
  );

  return (
    <>
      <Tooltip title="Change Avatar Model" placement="top">
        <IconButton
          ref={buttonRef}
          size="small"
          onClick={handleOpen}
          sx={{
            color: "rgba(245, 204, 127, 0.8)",
            "&:hover": {
              color: "#f5cc7f",
              background: "rgba(245, 204, 127, 0.1)",
            },
          }}
        >
          <SmartToyIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Menu
        anchorEl={menuAnchor}
        open={menuOpen}
        onClose={handleClose}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        slotProps={{
          paper: {
            sx: {
              mt: 1,
              minWidth: 200,
              maxHeight: 320,
              background: "rgba(18, 18, 22, 0.95)",
              backdropFilter: "blur(15px)",
              border: "1px solid rgba(245, 204, 127, 0.25)",
              boxShadow: "0 10px 30px rgba(0, 0, 0, 0.5)",
              "& .MuiMenuItem-root": {
                py: 1,
                px: 2,
                color: "rgba(255, 255, 255, 0.8)",
                fontSize: "0.875rem",
                "&:hover": {
                  background: "rgba(245, 204, 127, 0.12)",
                  color: "#f5cc7f",
                },
              },
            },
          },
        }}
      >
        <Box
          sx={{
            px: 2,
            py: 0.75,
            borderBottom: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          <Typography
            variant="caption"
            sx={{
              color: "rgba(245,204,127,0.7)",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontSize: "0.65rem",
            }}
          >
            Select Avatar
          </Typography>
        </Box>

        {vrmList.map((vrm, idx) => {
          const name = getVrmDisplayName(vrm.url);
          const isActive =
            currentVrm?.url === vrm.url ||
            currentVrm?.getHash() === vrm.getHash();

          return (
            <MenuItem
              key={vrm.url}
              selected={isActive}
              onClick={() => handleSelect(idx)}
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 1.5,
                "&.Mui-selected": {
                  background: "rgba(245, 204, 127, 0.15)",
                  color: "#f5cc7f",
                  "&:hover": {
                    background: "rgba(245, 204, 127, 0.22)",
                  },
                },
              }}
            >
              {/* Thumbnail placeholder – shows the model's thumb if available */}
              <Box
                sx={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background: "rgba(245, 204, 127, 0.12)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  overflow: "hidden",
                }}
              >
                {vrm.thumbUrl && vrm.thumbUrl !== "/vrm-assets/thumb-placeholder.jpg" ? (
                  <Box
                    component="img"
                    src={vrm.thumbUrl}
                    alt={name}
                    sx={{ width: "100%", height: "100%", objectFit: "cover" }}
                  />
                ) : (
                  <SmartToyIcon sx={{ fontSize: 14, color: "rgba(245,204,127,0.5)" }} />
                )}
              </Box>

              <Typography
                variant="body2"
                sx={{
                  flexGrow: 1,
                  fontWeight: isActive ? 600 : 400,
                }}
              >
                {name}
              </Typography>

              {isActive && (
                <Box
                  sx={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: "#f5cc7f",
                    flexShrink: 0,
                  }}
                />
              )}
            </MenuItem>
          );
        })}
      </Menu>
    </>
  );
}

export default memo(VrmModelSelector);
