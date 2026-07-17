'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const MonacoView = require('../../static/monaco-editor.js');

function createMockMonaco() {
  const models = new Map();
  const editors = [];
  const themes = [];
  const markers = new Map();
  const markerListeners = new Set();

  function uriKey(uri) { return uri.toString(); }

  function createModel(value, language, uri) {
    const listeners = new Set();
    const model = {
      uri,
      language,
      value,
      disposed: false,
      getValue() { return this.value; },
      setValue(next) {
        this.value = next;
        listeners.forEach((listener) => listener({ source: 'setValue' }));
      },
      userEdit(next) {
        this.value = next;
        listeners.forEach((listener) => listener({ source: 'user' }));
      },
      onDidChangeContent(listener) {
        listeners.add(listener);
        return { dispose() { listeners.delete(listener); } };
      },
      listenerCount() { return listeners.size; },
      dispose() {
        this.disposed = true;
        models.delete(uriKey(uri));
      }
    };
    models.set(uriKey(uri), model);
    return model;
  }

  const monaco = {
    KeyMod: { CtrlCmd: 2048, Shift: 1024 },
    KeyCode: { KeyS: 49, Space: 10, F2: 60, F12: 70 },
    Uri: {
      from(parts) {
        return {
          parts,
          toString() { return `${parts.scheme}://${parts.authority}${parts.path}`; }
        };
      }
    },
    editor: {
      create(_container, options) {
        const editor = {
          options: { ...options },
          model: null,
          commands: [],
          layoutCalls: 0,
          focusCalls: 0,
          disposed: false,
          actions: [],
          addCommand(keybinding, handler) { this.commands.push({ keybinding, handler }); },
          getAction(id) { return { run: () => { this.actions.push(id); } }; },
          setModel(model) { this.model = model; },
          setPosition(position) { this.position = position; },
          revealPositionInCenter(position) { this.revealedPosition = position; },
          updateOptions(next) { Object.assign(this.options, next); },
          layout() { this.layoutCalls += 1; },
          focus() { this.focusCalls += 1; },
          dispose() { this.disposed = true; }
        };
        editors.push(editor);
        return editor;
      },
      createModel,
      getModel(uri) { return models.get(uriKey(uri)) || null; },
      getModelMarkers({ resource }) { return markers.get(uriKey(resource)) || []; },
      onDidChangeMarkers(listener) {
        markerListeners.add(listener);
        return { dispose() { markerListeners.delete(listener); } };
      },
      setModelLanguage(model, language) { model.language = language; },
      setTheme(theme) { themes.push(theme); }
    },
    _models: models,
    _editors: editors,
    _themes: themes
  };
  monaco._setMarkers = function(uri, next) {
    markers.set(uriKey(uri), next);
    markerListeners.forEach((listener) => listener([uri]));
  };
  return monaco;
}

function createWindow() {
  const listeners = new Map();
  const observers = [];
  const events = [];
  class CustomEvent {
    constructor(type, options) { this.type = type; this.detail = options && options.detail; }
  }
  class ResizeObserver {
    constructor(callback) {
      this.callback = callback;
      this.disconnected = false;
      observers.push(this);
    }
    observe(target) { this.target = target; }
    disconnect() { this.disconnected = true; }
  }
  return {
    ResizeObserver,
    CustomEvent,
    events,
    observers,
    addEventListener(type, listener) { listeners.set(type, listener); },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) { listeners.delete(type); }
    },
    dispatchEvent(event) {
      events.push(event);
      const listener = listeners.get(event.type);
      if (listener) { listener(event); }
    }
  };
}

function createTextarea() {
  const listeners = new Map();
  return {
    hidden: true,
    disabled: true,
    value: '',
    focusCalls: 0,
    addEventListener(type, listener) { listeners.set(type, listener); },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) { listeners.delete(type); }
    },
    emit(type, event = {}) {
      const listener = listeners.get(type);
      if (listener) { listener(event); }
    },
    listenerCount() { return listeners.size; },
    focus() { this.focusCalls += 1; }
  };
}

function documentState(pathName, content = 'initial') {
  return {
    path: pathName,
    currentContent: content,
    savedContent: content
  };
}

function createAdapter(overrides = {}) {
  const monaco = overrides.monaco || createMockMonaco();
  const windowObject = overrides.windowObject || createWindow();
  const changes = [];
  const saves = [];
  const adapter = new MonacoView.MonacoEditorAdapter(monaco, {
    container: {},
    windowObject,
    onChange(pathName, content, modified) { changes.push({ pathName, content, modified }); },
    onSave() { saves.push(true); },
    lightTheme: false
  });
  return { adapter, monaco, windowObject, changes, saves };
}

test('mapea lenguajes conocidos y nombres especiales sin cargas remotas', () => {
  const expected = {
    'src/main.py': 'python',
    'app.js': 'javascript',
    'component.jsx': 'javascript',
    'main.ts': 'typescript',
    'component.tsx': 'typescript',
    'data.json': 'json',
    'index.html': 'html',
    'component.vue': 'html',
    'component.svelte': 'html',
    'diagram.xml': 'xml',
    'icon.svg': 'xml',
    'style.css': 'css',
    'README.md': 'markdown',
    'run.sh': 'shell',
    'config.yaml': 'yaml',
    'Dockerfile': 'dockerfile',
    'Makefile': 'plaintext',
    '.gitignore': 'plaintext',
    '.env.example': 'plaintext',
    'config.toml': 'plaintext',
    'unknown.xyz': 'plaintext'
  };
  for (const [file, language] of Object.entries(expected)) {
    assert.equal(MonacoView.languageForPath(file), language);
  }
});

test('cierra etiquetas compatibles como VS Code sin duplicar ni cerrar elementos vacíos', () => {
  assert.equal(
    MonacoView.closingTagForContext('html', 'index.html', '<main>', ''),
    '</main>'
  );
  assert.equal(
    MonacoView.closingTagForContext('javascript', 'component.jsx', '<Card.Item>', ''),
    '</Card.Item>'
  );
  assert.equal(
    MonacoView.closingTagForContext('typescript', 'component.tsx', '<Panel>', ''),
    '</Panel>'
  );
  assert.equal(MonacoView.closingTagForContext('html', 'index.html', '<img>', ''), '');
  assert.equal(MonacoView.closingTagForContext('html', 'index.html', '<main/>', ''), '');
  assert.equal(MonacoView.closingTagForContext('html', 'index.html', '<main>', '</main>'), '');
  assert.equal(MonacoView.closingTagForContext('javascript', 'app.js', '<main>', ''), '');
});

test('rechaza rutas absolutas, padres, barras invertidas y componentes ambiguos', () => {
  for (const value of ['/tmp/a.py', '../a.py', 'a/../b.py', 'a\\b.py', 'a//b.py', '']) {
    assert.throws(() => MonacoView.normalizeRelativePath(value), /invalid_relative_path/);
  }
});

test('crea URI estable con ruta relativa sin raíz absoluta ni contenido', () => {
  const monaco = createMockMonaco();
  const uri = MonacoView.createModelUri(monaco, 'src/main.py');
  assert.equal(uri.toString(), 'geram-workspace://local/src/main.py');
  assert.doesNotMatch(uri.toString(), /\/home\/|initial|token/i);
});

test('crear y volver a abrir el mismo archivo reutiliza un único modelo', () => {
  const { adapter, monaco } = createAdapter();
  const first = adapter.openDocument(documentState('a.py'));
  const second = adapter.openDocument(documentState('a.py'));
  assert.equal(first, second);
  assert.equal(monaco._models.size, 1);
  assert.equal(first.listenerCount(), 1);
});

test('dos archivos mantienen modelos y contenidos independientes', () => {
  const { adapter } = createAdapter();
  const first = adapter.openDocument(documentState('a.py', 'alpha'));
  first.userEdit('alpha local');
  const second = adapter.openDocument(documentState('b.js', 'beta'));
  second.userEdit('beta local');
  adapter.openDocument(documentState('a.py', 'server alpha'));
  assert.equal(adapter.getContent(), 'alpha local');
  assert.equal(adapter.getContent('b.js'), 'beta local');
});

test('cambio programático inicial no marca el documento como modificado', () => {
  const { adapter, changes } = createAdapter();
  adapter.openDocument(documentState('empty.txt', ''));
  adapter.setContent('loaded', { path: 'empty.txt', saved: true });
  assert.equal(adapter.isModified('empty.txt'), false);
  assert.equal(changes.length, 0);
});

test('cambio del usuario marca modificado y no mezcla otro modelo', () => {
  const { adapter, changes } = createAdapter();
  const first = adapter.openDocument(documentState('a.py', 'old'));
  adapter.openDocument(documentState('b.js', 'other'));
  first.userEdit('local');
  assert.deepEqual(changes.at(-1), { pathName: 'a.py', content: 'local', modified: true });
  assert.equal(adapter.getContent('b.js'), 'other');
});

test('marcar guardado limpia la comparación sólo para ese modelo', () => {
  const { adapter } = createAdapter();
  const model = adapter.openDocument(documentState('a.py', 'old'));
  model.userEdit('new');
  assert.equal(adapter.isModified(), true);
  adapter.markSaved('a.py', 'new');
  assert.equal(adapter.isModified(), false);
});

test('Ctrl+S o Cmd+S usa el comando único de guardado de Monaco', () => {
  const { adapter, monaco, saves } = createAdapter();
  const saveCommand = adapter.editor.commands.find((command) =>
    command.keybinding === (monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS));
  assert.ok(saveCommand);
  saveCommand.handler();
  assert.equal(saves.length, 1);
});

test('atajos profesionales invocan acciones reales integradas de Monaco', () => {
  const { adapter, monaco } = createAdapter();
  const expected = new Map([
    [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Space, 'editor.action.triggerSuggest'],
    [monaco.KeyCode.F12, 'editor.action.revealDefinition'],
    [monaco.KeyMod.Shift | monaco.KeyCode.F12, 'editor.action.goToReferences'],
    [monaco.KeyCode.F2, 'editor.action.rename']
  ]);
  for (const [keybinding, action] of expected) {
    const command = adapter.editor.commands.find((item) => item.keybinding === keybinding);
    assert.ok(command, action);
    command.handler();
    assert.equal(adapter.editor.actions.at(-1), action);
  }
});

test('markers reales se publican como Problemas navegables sin contenido del archivo', () => {
  const { adapter, monaco, windowObject } = createAdapter();
  const model = adapter.openDocument(documentState('src/main.ts', 'const value: string = 1;'));
  monaco._setMarkers(model.uri, [{
    severity: 8, message: "Type 'number' is not assignable to type 'string'.",
    source: 'ts', startLineNumber: 1, startColumn: 7
  }]);
  const event = windowObject.events.filter((item) => item.type === 'geram:problems').at(-1);
  assert.deepEqual(event.detail.problems, [{
    path: 'src/main.ts', severity: 8,
    message: "Type 'number' is not assignable to type 'string'.",
    source: 'ts', line: 1, column: 7
  }]);
  assert.equal(adapter.revealLocation('src/main.ts', 1, 7), true);
  assert.deepEqual(adapter.editor.position, { lineNumber: 1, column: 7 });
});

test('resize invoca layout y destruir libera observer, modelos y listeners', () => {
  const { adapter, windowObject } = createAdapter();
  const model = adapter.openDocument(documentState('a.py'));
  windowObject.observers[0].callback();
  assert.equal(adapter.editor.layoutCalls, 1);
  adapter.destroy();
  adapter.destroy();
  assert.equal(windowObject.observers[0].disconnected, true);
  assert.equal(adapter.editor.disposed, true);
  assert.equal(model.disposed, true);
  assert.equal(model.listenerCount(), 0);
});

test('cambio de tema actualiza Monaco sin recrear editor ni modelos', () => {
  const { adapter, monaco } = createAdapter();
  adapter.openDocument(documentState('a.py'));
  adapter.setTheme(true);
  adapter.setTheme(false);
  assert.deepEqual(monaco._themes, ['vs', 'geram-neon']);
  assert.equal(monaco._editors.length, 1);
  assert.equal(monaco._models.size, 1);
});

test('registra Emmet antes de crear Monaco y mantiene sugerencias activas', () => {
  const monaco = createMockMonaco();
  const windowObject = createWindow();
  const order = [];
  const create = monaco.editor.create;
  monaco.editor.create = function(container, options) {
    order.push('editor');
    return create(container, options);
  };
  windowObject.emmetMonaco = {
    emmetHTML(received, languages, options) {
      assert.equal(received, monaco);
      assert.deepEqual(languages, ['html', 'xml', 'javascript', 'typescript']);
      assert.deepEqual(options, { tokenizer: 'standard' });
      order.push('emmet-html');
    },
    emmetCSS(received, languages, options) {
      assert.equal(received, monaco);
      assert.deepEqual(languages, ['css']);
      assert.deepEqual(options, { tokenizer: 'standard' });
      order.push('emmet-css');
    }
  };

  const { adapter } = createAdapter({ monaco, windowObject });
  assert.deepEqual(order, ['emmet-html', 'emmet-css', 'editor']);
  assert.deepEqual(adapter.editor.options.quickSuggestions, {
    other: true,
    comments: false,
    strings: true
  });
  assert.equal(adapter.editor.options.suggestOnTriggerCharacters, true);
  assert.equal(adapter.editor.options.tabCompletion, 'on');
  assert.equal(adapter.editor.options.snippetSuggestions, 'inline');
  assert.equal(adapter.editor.options.parameterHints.enabled, true);
  assert.equal(adapter.editor.options.autoClosingBrackets, 'always');
  assert.equal(adapter.editor.options.autoClosingQuotes, 'always');
});

test('habilita diagnósticos semánticos locales y schema JSON sin red', () => {
  function defaults() {
    return {
      compiler: null, diagnostics: null, eager: false, options: null,
      setCompilerOptions(value) { this.compiler = value; },
      setDiagnosticsOptions(value) { this.diagnostics = value; },
      setEagerModelSync(value) { this.eager = value; },
      setOptions(value) { this.options = value; }
    };
  }
  const monaco = createMockMonaco();
  const javascriptDefaults = defaults();
  const typescriptDefaults = defaults();
  const htmlDefaults = defaults();
  const cssDefaults = defaults();
  const jsonDefaults = defaults();
  monaco.languages = {
    typescript: {
      ScriptTarget: { ES2020: 7 }, ModuleResolutionKind: { NodeJs: 2 },
      ModuleKind: { ESNext: 99 }, JsxEmit: { Preserve: 1 },
      javascriptDefaults, typescriptDefaults
    },
    html: { htmlDefaults }, css: { cssDefaults }, json: { jsonDefaults }
  };
  createAdapter({ monaco });
  assert.equal(javascriptDefaults.compiler.checkJs, true);
  assert.equal(javascriptDefaults.compiler.noEmit, true);
  assert.equal(javascriptDefaults.diagnostics.noSemanticValidation, false);
  assert.equal(typescriptDefaults.diagnostics.noSyntaxValidation, false);
  assert.equal(javascriptDefaults.eager, true);
  assert.deepEqual(htmlDefaults.options, { validate: true });
  assert.deepEqual(cssDefaults.options, { validate: true });
  assert.equal(jsonDefaults.diagnostics.enableSchemaRequest, false);
  assert.equal(jsonDefaults.diagnostics.schemas[0].uri, 'geram-schema://package-json');
  assert.deepEqual(jsonDefaults.diagnostics.schemas[0].fileMatch, ['package.json', '*/package.json']);
});

test('MonacoLoader inicializa AMD una sola vez', async () => {
  const monaco = createMockMonaco();
  let requireCalls = 0;
  let configCalls = 0;
  let loaderConfiguration = null;
  function amdRequire(_modules, resolve) {
    requireCalls += 1;
    windowObject.monaco = monaco;
    resolve();
  }
  amdRequire.config = (configuration) => {
    configCalls += 1;
    loaderConfiguration = configuration;
  };
  const windowObject = { require: amdRequire };
  const loader = new MonacoView.MonacoLoader();
  const [first, second] = await Promise.all([loader.load(windowObject), loader.load(windowObject)]);
  assert.equal(first, monaco);
  assert.equal(second, monaco);
  assert.equal(requireCalls, 1);
  assert.equal(configCalls, 1);
  assert.deepEqual(loaderConfiguration, {
    paths: { vs: '/vendor/monaco/vs' },
    preferScriptTags: true
  });
});

test('workers usan un bootstrap local explícito sin blob ni host externo', () => {
  const windowObject = {};
  MonacoView.configureMonacoEnvironment(windowObject);
  const workerUrl = windowObject.MonacoEnvironment.getWorkerUrl('workerMain.js', 'json');
  assert.equal(workerUrl, '/vendor/monaco/vs/base/worker/workerMain.js');
  assert.doesNotMatch(workerUrl, /^(?:https?:|blob:)|\/\//);
});

test('HTML referencia Monaco y Emmet sólo desde rutas locales vendorizadas', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '../../static/index.html'), 'utf8');
  const references = [...html.matchAll(/(?:src|href)="([^"]*monaco[^"]*)"/g)]
    .map((match) => match[1]);
  assert.deepEqual(references, [
    '/vendor/monaco/vs/editor/editor.main.css',
    '/vendor/monaco/vs/loader.js',
    '/vendor/emmet/emmet-monaco.min.js',
    'monaco-editor.js'
  ]);
  assert.equal(references.some((url) => /^(?:https?:)?\/\//.test(url)), false);
});

test('fallo de Monaco activa sólo el textarea de respaldo y conserva contenido', async () => {
  const textarea = createTextarea();
  const container = { hidden: false };
  const loadingElement = { hidden: true };
  let fallbackCode = '';
  const result = await MonacoView.initializeEditor({
    loader: { load: () => Promise.reject(new Error('controlled')) },
    windowObject: createWindow(),
    container,
    textarea,
    loadingElement,
    onFallback(code) { fallbackCode = code; }
  });
  assert.equal(result.fallback, true);
  assert.equal(fallbackCode, 'monaco_load_failed');
  assert.equal(container.hidden, true);
  assert.equal(textarea.hidden, false);
  result.adapter.openDocument(documentState('a.py', 'safe'));
  textarea.value = 'local';
  textarea.emit('input');
  assert.equal(result.adapter.getContent(), 'local');
});

test('fallback enruta Ctrl+S y Cmd+S sin listeners duplicados', async () => {
  const textarea = createTextarea();
  let saves = 0;
  const result = await MonacoView.initializeEditor({
    loader: { load: () => Promise.reject(new Error('controlled')) },
    windowObject: createWindow(),
    container: { hidden: false },
    textarea,
    loadingElement: { hidden: true },
    onSave() { saves += 1; }
  });
  const preventDefault = () => {};
  textarea.emit('keydown', { ctrlKey: true, metaKey: false, key: 's', preventDefault });
  textarea.emit('keydown', { ctrlKey: false, metaKey: true, key: 'S', preventDefault });
  assert.equal(saves, 2);
  assert.equal(textarea.listenerCount(), 2);
  result.adapter.destroy();
  assert.equal(textarea.listenerCount(), 0);
});

test('adaptador no usa almacenamiento del navegador ni registra contenido', () => {
  const source = fs.readFileSync(
    path.resolve(__dirname, '../../static/monaco-editor.js'),
    'utf8'
  );
  for (const forbidden of [
    'localStorage', 'sessionStorage', 'indexedDB', 'caches.', 'document.cookie', 'console.'
  ]) {
    assert.equal(source.includes(forbidden), false, forbidden);
  }
});
