'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const PythonLsp = require('../../static/python-lsp.js');
const ROOT = path.resolve(__dirname, '../..');

function uri(parts) {
  return { toString() { return `${parts.scheme}://${parts.authority}${parts.path}`; } };
}

function createClient() {
  const models = new Map();
  const markers = [];
  const providers = [];
  const monaco = {
    Uri: { from: uri },
    editor: {
      getModel(resource) { return models.get(resource.toString()) || null; },
      createModel(content, language, resource) {
        const model = { content, language, uri: resource, getLanguageId() { return language; }, getValue() { return content; } };
        models.set(resource.toString(), model);
        return model;
      },
      setModelMarkers(model, owner, value) { markers.push({ model, owner, value }); }
    },
    languages: new Proxy({}, {
      get(_target, name) {
        if (String(name).startsWith('register')) {
          return (language, provider) => {
            providers.push({ name, language, provider });
            return { dispose() {} };
          };
        }
      }
    })
  };
  const events = [];
  const socketEvents = new Map();
  const timers = new Map();
  let nextTimer = 0;
  const windowObject = {
    location: { protocol: 'http:', host: '127.0.0.1:8765' },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    dispatchEvent(event) { events.push(event); },
    WebSocket: class {
      constructor() { this.readyState = 0; }
      addEventListener(name, handler) { socketEvents.set(name, handler); }
      close() {}
      send() {}
    },
    setTimeout(callback) { const id = ++nextTimer; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); }
  };
  const controller = { editorReady: Promise.resolve({ models: new Map(), monaco }) };
  return {
    client: new PythonLsp.PythonLspClient(windowObject, controller, monaco),
    monaco, models, markers, providers, events, timers, socketEvents
  };
}

test('Pyright queda fijado exactamente, con licencia y sin carga en runtime', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'electron/package.json')));
  const lock = JSON.parse(fs.readFileSync(path.join(ROOT, 'electron/package-lock.json')));
  assert.equal(packageJson.devDependencies.pyright, '1.1.411');
  assert.equal(lock.packages['node_modules/pyright'].version, '1.1.411');
  assert.equal(lock.packages['node_modules/pyright'].license, 'MIT');
  assert.match(lock.packages['node_modules/pyright'].integrity, /^sha512-/);
  assert.match(fs.readFileSync(path.join(ROOT, 'electron/PYRIGHT_NOTICE.md'), 'utf8'), /pyright` 1\.1\.411/i);
  assert.match(fs.readFileSync(path.join(ROOT, 'electron/licenses/PYRIGHT-LICENSE.txt'), 'utf8'), /MIT License/);
});

test('posiciones, rangos, URI y símbolos se convierten de LSP a Monaco', () => {
  assert.deepEqual(PythonLsp.lspPosition({ lineNumber: 3, column: 5 }), { line: 2, character: 4 });
  assert.deepEqual(PythonLsp.monacoRange({ start: { line: 1, character: 2 }, end: { line: 3, character: 4 } }), {
    startLineNumber: 2, startColumn: 3, endLineNumber: 4, endColumn: 5
  });
  assert.equal(PythonLsp.relativeFromUri('file:///workspace/pkg/main.py'), 'pkg/main.py');
  assert.equal(PythonLsp.relativeFromUri('file:///etc/passwd'), '');
  const converted = PythonLsp.symbol({
    name: 'run', kind: 12,
    range: { start: { line: 0, character: 0 }, end: { line: 2, character: 0 } },
    selectionRange: { start: { line: 0, character: 4 }, end: { line: 0, character: 7 } },
    children: []
  });
  assert.equal(converted.kind, 11);
  assert.equal(converted.selectionRange.startColumn, 5);
});

test('registra providers Python reales para todas las operaciones editoriales', () => {
  const fixture = createClient();
  fixture.client.registerProviders();
  const names = fixture.providers.map((item) => item.name);
  for (const required of [
    'registerCompletionItemProvider', 'registerHoverProvider', 'registerSignatureHelpProvider',
    'registerDefinitionProvider', 'registerReferenceProvider', 'registerRenameProvider',
    'registerDocumentSymbolProvider'
  ]) assert.ok(names.includes(required), required);
  assert.ok(fixture.providers.every((item) => item.language === 'python'));
});

test('sincroniza apertura, cambios rápidos, guardado y cierre sin perder modelo por perfil', () => {
  const fixture = createClient();
  const sent = [];
  fixture.client.send = (message) => sent.push(message);
  fixture.client.modelEvent('open', { path: 'main.py', language: 'python', content: 'x = 1\n' });
  fixture.client.modelEvent('open', { path: 'main.py', language: 'python', content: 'x = 1\n' });
  fixture.client.modelEvent('change', { path: 'main.py', language: 'python', content: 'x = 2\n' });
  fixture.client.modelEvent('change', { path: 'main.py', language: 'python', content: 'x = 3\n' });
  assert.equal(sent.filter((item) => item.type === 'open').length, 1);
  assert.equal(fixture.timers.size, 1);
  fixture.client.modelEvent('save', { path: 'main.py', language: 'python', content: 'x = 3\n' });
  assert.equal(fixture.client.versions.get('main.py'), 3);
  assert.deepEqual(sent.slice(-2).map((item) => item.type), ['change', 'save']);
  assert.equal(sent.at(-1).type, 'save');
  fixture.client.modelEvent('close', { path: 'main.py', language: 'python' });
  assert.equal(fixture.client.versions.has('main.py'), false);
});

test('diagnósticos Pyright crean markers y alimentan el panel de Problemas', () => {
  const fixture = createClient();
  const resource = fixture.monaco.Uri.from({ scheme: 'geram-workspace', authority: 'local', path: '/main.py' });
  fixture.monaco.editor.createModel('', 'python', resource);
  fixture.client.updateDiagnostics('main.py', [{
    severity: 1, message: 'Type mismatch', code: 'reportArgumentType',
    range: { start: { line: 2, character: 4 }, end: { line: 2, character: 7 } }
  }]);
  assert.equal(fixture.markers[0].owner, 'pyright');
  assert.equal(fixture.markers[0].value[0].startLineNumber, 3);
  const event = fixture.events.find((item) => item.type === 'geram:python-problems');
  assert.equal(event.detail.problems[0].path, 'main.py');
  assert.equal(event.detail.problems[0].line, 3);
});

test('un crash descarta mensajes obsoletos y permite reabrir modelos al reconectar', () => {
  const fixture = createClient();
  fixture.client.connect();
  fixture.client.versions.set('main.py', 7);
  fixture.client.queue.push({ type: 'change', path: 'main.py' });
  fixture.client.changeTimers.set('main.py', fixture.client.windowObject.setTimeout(() => {}, 80));
  fixture.socketEvents.get('close')();
  assert.equal(fixture.client.ready, false);
  assert.equal(fixture.client.versions.size, 0);
  assert.equal(fixture.client.queue.length, 0);
  assert.equal(fixture.client.changeTimers.size, 0);
  assert.equal(fixture.timers.size, 1, 'queda sólo el reinicio controlado');
});

test('puente renderer sólo usa WebSocket local y endpoints acotados', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/python-lsp.js'), 'utf8');
  assert.match(source, /\/ws\/python-lsp/);
  assert.match(source, /\/api\/workspace\/file\?path=/);
  assert.doesNotMatch(source, /child_process|shell\s*:|https?:\/\/(?!127\.0\.0\.1)|eval\s*\(|npm install/);
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  assert.match(html, /<script src="python-lsp\.js"><\/script>/);
  assert.match(source, /var runtime = this\.windowObject/);
  assert.doesNotMatch(source, /var timeout = windowObject\.setTimeout/);
});
