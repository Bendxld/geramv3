const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');
const test = require('node:test');

const ROOT = path.join(__dirname, '..', '..');
const STATIC = path.join(ROOT, 'static');
const ELECTRON = path.join(ROOT, 'electron', 'node_modules', '.bin', 'electron');
const APP = path.join(__dirname, 'ui-click-smoke-app.js');

function json(response, value) {
  response.writeHead(200, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify(value));
}

function fixture(pathname) {
  if (pathname === '/api/runtime/status') return {
    user: { name: 'Smoke user' },
    roles: { iris: { provider: 'gemini', configured: true }, ares: { provider: 'ollama', configured: true } },
    ollama_available: true,
    integrations: [],
    agents: { enabled: 2, total: 2, loaded: 0 },
    media: { pdf_text: true, provider_audio: true, local_whisper: false, browser_tts: true },
    state: { voice_enabled: true, vision_enabled: false, offline_forced: false },
  };
  if (pathname === '/info') return { instancia: 'IRIS', agentes_activos: [] };
  if (pathname === '/api/agents/roster') return {
    agents: [
      { id: 'bundled:director', nombre: 'director', etiqueta: 'Director', enabled: true, loaded: false, core: true, nucleo: true, origin: 'bundled' },
      { id: 'bundled:spotify_agent', nombre: 'spotify_agent', etiqueta: 'Spotify', enabled: true, loaded: false, core: false, nucleo: false, origin: 'bundled' },
    ],
  };
  if (pathname === '/api/gcs/agents' || pathname === '/api/gcs/skills') return { agents: [], skills: [] };
  if (pathname === '/api/gcs/integrations') return { integrations: [] };
  if (pathname === '/api/runtime/state') return { voice_enabled: true, vision_enabled: false, offline_forced: false };
  if (pathname === '/api/config') return {
    user_profile: { name: 'Smoke user', age: null, system_prompt_override: '', use_tts_notifications: false },
    ui_theme: { primary_color: '#e84393', background_color: '#0a0a0f', accent_color: '#8d1f68', core_identity_view: 'core' },
    privacy_controls: { blocked_paths: ['.env'], developer_mode: false },
    onboarding: { manual_version_seen: 999, setup_version_seen: 999 },
  };
  if (pathname === '/config/providers') return [];
  if (pathname === '/config/keys') return {};
  if (pathname === '/config/provider-keys') return { credentials: [] };
  if (pathname === '/api/workspace/status') return { developer_mode: false, workspace_label: 'Smoke workspace' };
  if (pathname === '/api/workspace/tree') return { entries: [] };
  return {};
}

function contentType(filename) {
  if (filename.endsWith('.html')) return 'text/html; charset=utf-8';
  if (filename.endsWith('.js')) return 'text/javascript; charset=utf-8';
  if (filename.endsWith('.css')) return 'text/css; charset=utf-8';
  if (filename.endsWith('.svg')) return 'image/svg+xml';
  if (filename.endsWith('.json')) return 'application/json';
  if (filename.endsWith('.woff2')) return 'font/woff2';
  return 'application/octet-stream';
}

test('Electron opens the real HUD and clicks Agents and Settings', { timeout: 30000 }, async (t) => {
  if (!process.env.DISPLAY || !fs.existsSync(ELECTRON)) {
    t.skip('A graphical Electron runtime is not available.');
    return;
  }
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1');
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/config/') || url.pathname === '/info') {
      json(response, fixture(url.pathname));
      return;
    }
    const relative = url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.slice(1));
    const filename = path.resolve(STATIC, relative);
    if (!filename.startsWith(STATIC + path.sep) || !fs.existsSync(filename) || !fs.statSync(filename).isFile()) {
      response.writeHead(404); response.end('not found'); return;
    }
    response.writeHead(200, { 'Content-Type': contentType(filename) });
    fs.createReadStream(filename).pipe(response);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const address = server.address();

  const output = await new Promise((resolve, reject) => {
    const child = spawn(ELECTRON, [APP, `http://127.0.0.1:${address.port}/`], {
      cwd: ROOT,
      env: { ...process.env, ELECTRON_DISABLE_SECURITY_WARNINGS: 'true' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code !== 0) reject(new Error(stderr || `Electron exited ${code}`));
      else resolve(stdout);
    });
  });
  const match = output.match(/GERAM_UI_SMOKE=(\{[^\n]+\})/);
  assert.ok(match, output);
  const result = JSON.parse(match[1]);
  assert.deepEqual(result, {
    agentsOpen: true,
    agentCount: '2/2',
    settingsOpen: true,
    runtimeReady: true,
  });
});
