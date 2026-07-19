const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'runtime-status.js'),
  'utf8'
);

function classList() {
  const values = new Set();
  return {
    add(value) { values.add(value); },
    toggle(value, enabled) { if (enabled) values.add(value); else values.delete(value); },
    contains(value) { return values.has(value); },
  };
}

test('runtime status updates the real per-user UI and completes boot', async () => {
  const elements = {
    boot: { classList: classList() },
    bootLog: { textContent: '' },
    'btn-voz': { classList: classList() },
    'btn-vista': { classList: classList() },
    runtimeUserSummary: { textContent: '' },
  };
  const body = { classList: classList() };
  const pill = { lastChild: { textContent: '' } };
  const logs = [];
  let infoLoads = 0;
  const payload = {
    user: { name: 'Ada' },
    roles: {
      iris: { provider: 'gemini', configured: true },
      ares: { provider: 'ollama', configured: true },
    },
    ollama_available: true,
    integrations: [
      { id: 'obsidian', name: 'Obsidian', state: 'connected' },
      { id: 'spotify', name: 'Spotify', state: 'available' },
    ],
    agents: { enabled: 42, total: 44, loaded: 2 },
    media: { pdf_text: true, provider_audio: true, local_whisper: false, browser_tts: true },
    state: { voice_enabled: false, vision_enabled: true, offline_forced: false },
  };

  const windowObject = {
    document: {
      body,
      getElementById(id) { return elements[id] || null; },
      querySelector(selector) { return selector === '.estado-pill' ? pill : null; },
    },
    fetch: async () => ({ ok: true, json: async () => payload }),
    geramLog(message) { logs.push(message); },
    cargarInfo() { infoLoads += 1; },
    setInterval(callback) {
      const id = { active: true };
      queueMicrotask(() => {
        for (let index = 0; index < 30 && id.active; index += 1) callback();
      });
      return id;
    },
    clearInterval(id) { id.active = false; },
    setTimeout(callback) { queueMicrotask(callback); },
    clearTimeout() {},
  };
  windowObject.window = windowObject;

  vm.runInNewContext(source, windowObject, { filename: 'runtime-status.js' });
  for (let index = 0; index < 8; index += 1) await Promise.resolve();

  assert.equal(elements['btn-voz'].classList.contains('activo'), false);
  assert.equal(elements['btn-vista'].classList.contains('activo'), true);
  assert.match(elements.runtimeUserSummary.textContent, /ADA/);
  assert.match(elements.bootLog.textContent, /AGENTS ENABLED .*42\/44/);
  assert.doesNotMatch(elements.bootLog.textContent, /SUPABASE .* OK|5\/5 NODES|RANDOM/i);
  assert.equal(body.classList.contains('listo'), true);
  assert.equal(elements.boot.classList.contains('fuera'), true);
  assert.equal(infoLoads, 1);
  assert.ok(logs.some((line) => line.includes('OBSIDIAN: CONNECTED')));
});
