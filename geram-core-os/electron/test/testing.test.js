'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const Testing = require('../../static/testing.js');
const ROOT = path.resolve(__dirname, '../..');

test('estados de ejecución son claros y claves separan runner, archivo y selector', () => {
  assert.equal(Testing.statusLabel('queued'), 'QUEUED');
  assert.equal(Testing.statusLabel('running'), 'RUNNING');
  assert.equal(Testing.statusLabel('succeeded'), 'PASSED');
  assert.equal(Testing.statusLabel('failed'), 'FAILED');
  assert.equal(Testing.statusLabel('cancelled'), 'CANCELLED');
  assert.equal(Testing.resultKey({ runner: 'python_unittest', path: 'test_a.py', selector: 'T.test_a' }), 'python_unittest|test_a.py|T.test_a');
});

test('resultados se remapean en rename y ubicación de traceback es navegable', () => {
  assert.equal(Testing.remapPath('tests/a.py', [{ oldPath: 'tests', newPath: 'specs', type: 'directory' }]), 'specs/a.py');
  assert.equal(Testing.remapPath('other/a.py', [{ oldPath: 'tests', newPath: 'specs', type: 'directory' }]), 'other/a.py');
  assert.deepEqual(Testing.failureLocation('Traceback\n  File "/workspace/tests/test_a.py", line 14, in test_bad', 'tests/test_a.py'), { path: 'tests/test_a.py', line: 14, column: 1 });
  assert.equal(Testing.isRemovedPath('tests/test_a.py', [{ path: 'tests', type: 'directory' }]), true);
  assert.equal(Testing.isRemovedPath('tests/test_a.py', [{ path: 'other.py', type: 'file' }]), false);
});

test('UI usa exclusivamente Testing API y Terminal Watcher', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/testing.js'), 'utf8');
  for (const token of [
    '/api/testing/discovery', '/api/testing/runs', '/api/terminal-watcher/runs/',
    'python_unittest', 'python_file', 'node_script', 'Run all', 'Repeat last',
    'Clear results', 'sandbox_backend:', 'cleanup_status:'
  ]) assert.ok(source.includes(token), token);
  assert.match(source, /cleanup_status === 'pending'/);
  assert.match(source, /currentRunId !== requestedRunId/);
  assert.doesNotMatch(source, /innerHTML|eval\s*\(|child_process|https?:\/\//);
});

test('dirty files requieren guardado y branch/profile no destruyen estado', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/testing.js'), 'utf8');
  assert.match(source, /There are unsaved changes/);
  assert.match(source, /controller\.save\(\)/);
  assert.match(source, /geram:workspace-paths-changed/);
  assert.doesNotMatch(source, /perfil-(?:iris|ares).*results\.clear/);
});

test('CodeLens reales se registran para clases y métodos Python', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/testing.js'), 'utf8');
  assert.match(source, /registerCodeLensProvider\('python'/);
  assert.match(source, /monaco\.editor\.registerCommand\('geram\.testing\.run'/);
  assert.match(source, /▷ Run/);
});

test('assets Testing son locales y cargan después del workspace', () => {
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  assert.match(html, /testing\.css/);
  assert.match(html, /testing\.js/);
  assert.match(html, /id="toggleTesting"/);
  assert.ok(html.indexOf('workspace.js') < html.indexOf('testing.js'));
  assert.doesNotMatch(fs.readFileSync(path.join(ROOT, 'static/testing.css'), 'utf8'), /https?:\/\//);
});
