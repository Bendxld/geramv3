'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const FileOperations = require('../../static/workspace-file-operations.js');
const MonacoView = require('../../static/monaco-editor.js');
const Navigation = require('../../static/workspace-navigation.js');
const PythonLsp = require('../../static/python-lsp.js');
const ROOT = path.resolve(__dirname, '../..');

test('helpers sólo construyen nombres y rutas relativas previsibles', () => {
  assert.equal(FileOperations.parentPath('src/lib/main.js'), 'src/lib');
  assert.equal(FileOperations.basename('src/lib/main.js'), 'main.js');
  assert.equal(FileOperations.duplicateName('src/main.js'), 'main copy.js');
  assert.equal(FileOperations.duplicateName('README'), 'README copy');
  assert.equal(FileOperations.remapPath('src/lib/a.py', 'src', 'source', 'directory'), 'source/lib/a.py');
  assert.equal(FileOperations.remapPath('src2/a.py', 'src', 'source', 'directory'), 'src2/a.py');
});

test('dirty guard incluye archivo o subárbol sin descartar cambios', () => {
  const documents = new Map([
    ['src/a.py', { path: 'src/a.py', modified: true }],
    ['src/b.py', { path: 'src/b.py', modified: false }],
    ['other.py', { path: 'other.py', modified: true }]
  ]);
  assert.deepEqual(FileOperations.dirtyPathsFor(documents, 'src', 'directory'), ['src/a.py']);
  assert.deepEqual(FileOperations.dirtyPathsFor(documents, 'other.py', 'file'), ['other.py']);
});

test('cerrar modelos elimina markers y emite didClose para Pyright', () => {
  const events = [];
  const model = {
    uri: { toString() { return 'file://workspace/src/main.py'; } },
    getLanguageId() { return 'python'; },
    dispose() { this.disposed = true; }
  };
  const record = { model, changeSubscription: { dispose() { this.disposed = true; } } };
  const adapter = Object.create(MonacoView.MonacoEditorAdapter.prototype);
  adapter.models = new Map([['src/main.py', record]]);
  adapter.activePath = 'src/main.py';
  adapter.windowObject = {
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    dispatchEvent(event) { events.push(event); }
  };
  adapter.monaco = {
    Uri: { from() { return model.uri; } },
    editor: {
      getModel() { return model; },
      setModelMarkers(target, owner, markers) { events.push({ target, owner, markers }); }
    }
  };
  adapter.editor = { setModel(value) { this.model = value; }, updateOptions() {} };
  adapter.publishProblems = function() { events.push({ type: 'problems' }); };
  adapter.closeDocuments(['src/main.py']);
  assert.equal(adapter.models.size, 0);
  assert.equal(model.disposed, true);
  assert.equal(adapter.activePath, '');
  assert.ok(events.some((event) => event.type === 'geram:model-close' && event.detail.path === 'src/main.py'));
  assert.deepEqual(events.filter((event) => event.owner).map((event) => event.owner), ['pyright', 'javascript', 'typescript']);
});

test('Pyright elimina diagnósticos de la URI cerrada', () => {
  const events = [], sent = [];
  const client = Object.create(PythonLsp.PythonLspClient.prototype);
  client.versions = new Map([['old.py', 1]]);
  client.changeTimers = new Map();
  client.diagnostics = new Map([
    ['old.py', [{ path: 'old.py' }]],
    ['kept.py', [{ path: 'kept.py' }]]
  ]);
  client.send = (message) => sent.push(message);
  client.windowObject = {
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    dispatchEvent(event) { events.push(event); },
    clearTimeout() {}
  };
  client.modelEvent('close', { path: 'old.py', language: 'python' });
  assert.equal(client.diagnostics.has('old.py'), false);
  assert.equal(sent.at(-1).type, 'close');
  assert.deepEqual(events.at(-1).detail.problems, [{ path: 'kept.py' }]);
});

test('historial se remapea o limpia después de mover y eliminar', () => {
  const history = new Navigation.NavigationHistory(20);
  history.push({ path: 'src/a.py', line: 1, column: 1 });
  history.push({ path: 'src/pkg/b.py', line: 2, column: 1 });
  history.remap('src', 'source', 'directory');
  assert.deepEqual(history.entries.map((entry) => entry.path), ['source/a.py', 'source/pkg/b.py']);
  history.remove('source/pkg', 'directory');
  assert.deepEqual(history.entries.map((entry) => entry.path), ['source/a.py']);
});

test('UI usa API cerrada, aprobación, drag and drop y assets locales', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/workspace-file-operations.js'), 'utf8');
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  for (const token of [
    '/api/workspace/operations/create', '/api/workspace/operations/duplicate',
    '/api/workspace/operations/move/preview', '/api/workspace/operations/move/apply',
    '/api/workspace/operations/delete/preview', '/api/workspace/operations/delete/apply',
    'dragstart', 'drop', 'unsaved changes', 'Copy relative path'
  ]) assert.ok(source.includes(token), token);
  assert.match(html, /workspace-file-operations\.css/);
  assert.match(html, /workspace-file-operations\.js/);
  assert.doesNotMatch(source, /innerHTML|eval\s*\(|https?:\/\//);
});
