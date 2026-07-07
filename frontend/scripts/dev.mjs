#!/usr/bin/env node
/**
 * Local dev startup with a backend-readiness check — no Docker involved on
 * the frontend side at all (there never was anything to containerize here
 * except the final deployable build). Node/ESM, so it runs identically on
 * Windows/macOS/Linux.
 *
 * The single most common local-dev failure mode across two separate repos
 * is starting the frontend before the backend — it doesn't error clearly,
 * it just produces a wall of CORS/network errors in the browser console
 * that look like a frontend bug. This script catches that explicitly.
 */
import { existsSync, copyFileSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

function readEnvVar(name, fallback) {
  const envPath = path.join(ROOT, '.env');
  if (!existsSync(envPath)) return fallback;
  const line = readFileSync(envPath, 'utf-8')
    .split('\n')
    .find((l) => l.trim().startsWith(`${name}=`));
  if (!line) return fallback;
  // Strip a trailing inline comment the same defensive way the backend
  // project's .env.example note calls out — only matters if a value is
  // ever left blank with a trailing "# ..." note, but cheap to handle here.
  const value = line.slice(line.indexOf('=') + 1).split(' #')[0].trim();
  return value || fallback;
}

function ensureEnvFile() {
  const envPath = path.join(ROOT, '.env');
  const examplePath = path.join(ROOT, '.env.example');
  if (!existsSync(envPath)) {
    copyFileSync(examplePath, envPath);
    console.log('⚠️  No .env found — created one from .env.example.');
  }
}

async function waitForBackend(url, timeoutMs = 10000, intervalMs = 500) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fetch(url, { signal: AbortSignal.timeout(2000) });
      return true;
    } catch {
      process.stdout.write('.');
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }
  return false;
}

async function main() {
  ensureEnvFile();
  // VITE_API_BASE_URL is what the *browser* uses (always http://localhost:8000
  // from the host's point of view, Docker or not — Vite serves it to the
  // client, which never runs inside a container). This script's own health
  // check, though, runs wherever dev.mjs itself runs — which, when started
  // via docker-compose, is *inside* the frontend container, where
  // "localhost" means the frontend container, not the backend one. Compose
  // sets BACKEND_HEALTH_CHECK_URL to the internal service address
  // (http://backend:8000) specifically to cover that case; it's unset (and
  // falls back to VITE_API_BASE_URL) for native/non-Docker dev.
  const apiBaseUrl = readEnvVar('VITE_API_BASE_URL', 'http://localhost:8000');
  const healthCheckUrl = process.env.BACKEND_HEALTH_CHECK_URL || apiBaseUrl;
  const healthUrl = `${healthCheckUrl}/health`;

  console.log(`Checking backend at ${healthUrl} ...`);
  const ready = await waitForBackend(healthUrl, 30000);
  console.log();

  if (!ready) {
    console.error(`❌ Can't reach the backend at ${healthUrl}\n`);
    console.error('Start the backend first:');
    console.error('  cd ../backend && python scripts/dev.py   (no Docker)');
    console.error('  docker compose up backend                (Docker)\n');
    console.error('Then re-run this script.');
    process.exit(1);
  }

  console.log(`✅ Backend reachable at ${healthCheckUrl} — starting frontend\n`);
  console.log('Frontend:  http://localhost:3000\n');

  const vite = spawn('npx', ['vite'], {
    cwd: ROOT,
    stdio: 'inherit',
    shell: true,
  });

  vite.on('exit', (code) => process.exit(code ?? 0));
}

main();
