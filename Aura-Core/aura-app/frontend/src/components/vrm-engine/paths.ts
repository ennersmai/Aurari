export const vrmList = [
  "/vrm-assets/AvatarSample_A.vrm",
  "/vrm-assets/AvatarSample_B.vrm",
  "/vrm-assets/AvatarSample_C.vrm",
  "/vrm-assets/AvatarSample_D.vrm",
  "/vrm-assets/Aera.vrm",
  "/vrm-assets/Dhahlia.vrm",
  "/vrm-assets/Epithet.vrm",
  "/vrm-assets/Lara Lightland.vrm",
  "/vrm-assets/Onyx.vrm",
  "/vrm-assets/Velara.vrm",
];

/** Display-friendly names for each VRM model path. */
export const vrmDisplayNames: Record<string, string> = {
  "/vrm-assets/AvatarSample_A.vrm": "Avatar Sample A",
  "/vrm-assets/AvatarSample_B.vrm": "Avatar Sample B",
  "/vrm-assets/AvatarSample_C.vrm": "Avatar Sample C",
  "/vrm-assets/AvatarSample_D.vrm": "Avatar Sample D",
  "/vrm-assets/Aera.vrm": "Aera",
  "/vrm-assets/Dhahlia.vrm": "Dhahlia",
  "/vrm-assets/Epithet.vrm": "Epithet",
  "/vrm-assets/Lara Lightland.vrm": "Lara Lightland",
  "/vrm-assets/Onyx.vrm": "Onyx",
  "/vrm-assets/Velara.vrm": "Velara",
};

/** Get a display-friendly name for a VRM path. */
export function getVrmDisplayName(url: string): string {
  return vrmDisplayNames[url] ?? url.split("/").pop()?.replace(".vrm", "") ?? url;
}

