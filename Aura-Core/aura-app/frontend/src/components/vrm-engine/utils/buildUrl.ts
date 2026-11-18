/**
 * Asset URL resolver.
 *
 * Prepends NEXT_PUBLIC_BASE_PATH when set (Docker / Tauri / sub-path deployments).
 * Falls back to the raw path for local dev (Next.js serves /public directly).
 */
export function buildUrl(path: string): string {
  const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
  return `${basePath}${path}`;
}
