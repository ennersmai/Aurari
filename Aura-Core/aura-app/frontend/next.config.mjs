/**
 * Next.js configuration for Aura frontend.
 *
 * The util._extend patch is loaded here (first thing Next.js evaluates)
 * so we don't need NODE_OPTIONS, which leaks into VS Code's Electron
 * process and produces noisy warnings.
 */
// eslint-disable-next-line @typescript-eslint/no-require-imports
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
require('./src/utils/patch-util-extend.js');

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Turbopack is used in dev mode (--turbopack flag in package.json scripts)
};

export default nextConfig;
