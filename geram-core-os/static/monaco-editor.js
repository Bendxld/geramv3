/* GERAM CORE OS Monaco adapter.
 *
 * Monaco is loaded only from the vendored same-origin AMD runtime. This module
 * owns editor models and view listeners; workspace.js remains responsible for
 * paths, versions, API calls, conflicts, and user-facing state.
 */
(function(root, factory) {
  'use strict';
  var exported = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = exported;
  }
  if (root) { root.GeramMonacoEditor = exported; }
})(typeof window !== 'undefined' ? window : null, function() {
  'use strict';

  var MONACO_BASE = '/vendor/monaco/vs';
  var WORKER_BOOTSTRAP = MONACO_BASE + '/base/worker/workerMain.js';

  function normalizeRelativePath(path) {
    if (typeof path !== 'string' || !path || path.charAt(0) === '/' || path.indexOf('\\') !== -1) {
      throw new TypeError('invalid_relative_path');
    }
    var parts = path.split('/');
    if (parts.some(function(part) { return !part || part === '.' || part === '..' || part.indexOf('\0') !== -1; })) {
      throw new TypeError('invalid_relative_path');
    }
    return parts.join('/');
  }

  function languageForPath(path) {
    var normalized = normalizeRelativePath(path);
    var name = normalized.slice(normalized.lastIndexOf('/') + 1);
    var lowerName = name.toLowerCase();
    var extensionIndex = lowerName.lastIndexOf('.');
    var extension = extensionIndex >= 0 ? lowerName.slice(extensionIndex) : '';

    if (lowerName === 'dockerfile') { return 'dockerfile'; }
    if (lowerName === 'makefile' || lowerName === '.gitignore' || lowerName === '.env.example') {
      return 'plaintext';
    }

    var languages = {
      '.py': 'python',
      '.js': 'javascript',
      '.mjs': 'javascript',
      '.cjs': 'javascript',
      '.jsx': 'javascript',
      '.ts': 'typescript',
      '.tsx': 'typescript',
      '.json': 'json',
      '.html': 'html',
      '.htm': 'html',
      '.vue': 'html',
      '.svelte': 'html',
      '.xml': 'xml',
      '.svg': 'xml',
      '.css': 'css',
      '.md': 'markdown',
      '.markdown': 'markdown',
      '.sh': 'shell',
      '.bash': 'shell',
      '.yaml': 'yaml',
      '.yml': 'yaml',
      '.toml': 'plaintext',
      '.txt': 'plaintext'
    };
    return languages[extension] || 'plaintext';
  }

  // Tema oscuro "GERAM Neon": acentos rosa/morado eléctrico y resalte de
  // alto contraste para Python/JS/HTML/CSS/JSON. Se define una sola vez.
  var geramThemeDefined = false;
  function defineGeramTheme(monaco) {
    if (geramThemeDefined) { return; }
    if (!monaco || !monaco.editor || typeof monaco.editor.defineTheme !== 'function') { return; }
    geramThemeDefined = true;
    monaco.editor.defineTheme('geram-neon', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: '', foreground: 'e8e6f0' },
        { token: 'comment', foreground: '6b6580', fontStyle: 'italic' },
        { token: 'keyword', foreground: 'ff5db1', fontStyle: 'bold' },
        { token: 'keyword.control', foreground: 'ff5db1', fontStyle: 'bold' },
        { token: 'string', foreground: 'a6f0c6' },
        { token: 'number', foreground: 'c792ea' },
        { token: 'regexp', foreground: 'ff8bcf' },
        { token: 'type', foreground: '82aaff' },
        { token: 'type.identifier', foreground: '82aaff' },
        { token: 'function', foreground: '82e9ff' },
        { token: 'variable', foreground: 'e8e6f0' },
        { token: 'variable.predefined', foreground: 'c792ea' },
        { token: 'constant', foreground: 'c792ea' },
        { token: 'delimiter', foreground: 'b8b0d0' },
        { token: 'tag', foreground: 'ff5db1' },
        { token: 'attribute.name', foreground: '82e9ff' },
        { token: 'attribute.value', foreground: 'a6f0c6' },
        { token: 'key', foreground: '82e9ff' }
      ],
      colors: {
        'editor.background': '#0d0b12',
        'editor.foreground': '#e8e6f0',
        'editorCursor.foreground': '#ff5db1',
        'editor.lineHighlightBackground': '#1a16261a',
        'editor.selectionBackground': '#3a2a52',
        'editorLineNumber.foreground': '#5a5470',
        'editorLineNumber.activeForeground': '#ff5db1',
        'editorIndentGuide.background': '#241f33',
        'editorGutter.background': '#0d0b12',
        'minimap.background': '#0b0910',
        'editorWidget.background': '#141020',
        'editorBracketMatch.border': '#ff5db1'
      }
    });
  }

  // IntelliSense de JS/TS: Monaco trae los language services vendorizados;
  // aquí solo se afinan las opciones del compilador. Defensivo para el mock
  // de tests (sin monaco.languages).
  var languageDefaultsDone = false;
  var LOCAL_PACKAGE_JSON_SCHEMA = {
    uri: 'geram-schema://package-json',
    fileMatch: ['package.json', '*/package.json'],
    schema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Nombre local del paquete.' },
        version: { type: 'string', description: 'Semantic package version.' },
        private: { type: 'boolean', description: 'Prevents accidental publishing.' },
        type: { enum: ['commonjs', 'module'], description: 'Node.js module system.' },
        main: { type: 'string', description: 'Punto de entrada principal.' },
        scripts: { type: 'object', additionalProperties: { type: 'string' } }
      },
      additionalProperties: true
    }
  };
  function configureLanguageDefaults(monaco) {
    if (languageDefaultsDone) { return; }
    if (!monaco.languages || !monaco.languages.typescript) { return; }
    languageDefaultsDone = true;
    try {
      var ts = monaco.languages.typescript;
      var compilerOptions = {
        target: ts.ScriptTarget.ES2020,
        allowNonTsExtensions: true,
        allowJs: true,
        checkJs: true,
        noEmit: true,
        moduleResolution: ts.ModuleResolutionKind.NodeJs,
        module: ts.ModuleKind.ESNext,
        jsx: ts.JsxEmit.Preserve
      };
      ts.javascriptDefaults.setCompilerOptions(compilerOptions);
      ts.typescriptDefaults.setCompilerOptions(compilerOptions);
      ts.javascriptDefaults.setEagerModelSync(true);
      ts.typescriptDefaults.setEagerModelSync(true);
      var diagnostics = {
        noSemanticValidation: false,
        noSyntaxValidation: false,
        noSuggestionDiagnostics: false,
        onlyVisible: false
      };
      ts.javascriptDefaults.setDiagnosticsOptions(diagnostics);
      ts.typescriptDefaults.setDiagnosticsOptions(diagnostics);
      if (monaco.languages.html && monaco.languages.html.htmlDefaults) {
        monaco.languages.html.htmlDefaults.setOptions({ validate: true });
      }
      if (monaco.languages.css && monaco.languages.css.cssDefaults) {
        monaco.languages.css.cssDefaults.setOptions({ validate: true });
      }
      if (monaco.languages.json && monaco.languages.json.jsonDefaults) {
        monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
          validate: true,
          allowComments: false,
          enableSchemaRequest: false,
          schemas: [LOCAL_PACKAGE_JSON_SCHEMA]
        });
      }
    } catch (e) { /* entorno sin TS: se ignora */ }
  }

  // Emmet para HTML y CSS (bundle vendorizado emmet-monaco-es, global
  // window.emmetMonaco). Expande abreviaciones (ul>li*3, div.card) con Tab.
  // Se registra una sola vez; defensivo si el bundle o window no existen.
  var emmetDone = false;
  function registerEmmet(monaco, windowObject) {
    if (emmetDone) { return; }
    if (!windowObject || !windowObject.emmetMonaco) { return; }
    emmetDone = true;
    try {
      // Monaco 0.52 puede mantener nulo su tokenizer Monarch privado hasta
      // después del primer ciclo de fondo. El modo standard usa la API pública
      // de tokens y evita que Emmet rompa el provider de sugerencias.
      var tokenizerOptions = { tokenizer: 'standard' };
      windowObject.emmetMonaco.emmetHTML(
        monaco,
        ['html', 'xml', 'javascript', 'typescript'],
        tokenizerOptions
      );
      windowObject.emmetMonaco.emmetCSS(monaco, ['css'], tokenizerOptions);
    } catch (e) { /* emmet no disponible: se ignora */ }
  }

  // Auto-cerrar etiquetas HTML/XML al escribir ">", estilo VS Code.
  var VOID_TAGS = { area: 1, base: 1, br: 1, col: 1, embed: 1, hr: 1, img: 1, input: 1, link: 1, meta: 1, param: 1, source: 1, track: 1, wbr: 1 };
  function closingTagForContext(language, path, before, after) {
    var normalizedPath = String(path || '').toLowerCase();
    var tagFile = language === 'html' || language === 'xml' ||
      /\.(?:jsx|tsx|vue|svelte|svg|xml|html?)$/.test(normalizedPath);
    if (!tagFile || /\/>$/.test(before)) { return ''; }
    var match = String(before || '').match(/<([a-zA-Z][\w:.-]*)(?:\s[^<>]*?)?>$/);
    if (!match) { return ''; }
    var tag = match[1];
    if (VOID_TAGS[tag.toLowerCase()]) { return ''; }
    var closing = '</' + tag + '>';
    if (String(after || '').indexOf(closing) === 0) { return ''; }
    return closing;
  }

  function installAutoCloseTags(monaco, adapterInstance) {
    var editor = adapterInstance.editor;
    if (!editor || typeof editor.onDidType !== 'function' || !monaco.Range) { return; }
    editor.onDidType(function (text) {
      if (text !== '>') { return; }
      var model = editor.getModel();
      if (!model || typeof model.getLanguageId !== 'function') { return; }
      var lang = model.getLanguageId();
      var pos = editor.getPosition();
      var before = model.getValueInRange({ startLineNumber: pos.lineNumber, startColumn: 1, endLineNumber: pos.lineNumber, endColumn: pos.column });
      var lineEnd = typeof model.getLineMaxColumn === 'function' ?
        model.getLineMaxColumn(pos.lineNumber) : pos.column;
      var after = model.getValueInRange({
        startLineNumber: pos.lineNumber,
        startColumn: pos.column,
        endLineNumber: pos.lineNumber,
        endColumn: lineEnd
      });
      var closing = closingTagForContext(lang, adapterInstance.activePath, before, after);
      if (!closing) { return; }
      editor.executeEdits('autoCloseTag', [{
        range: new monaco.Range(pos.lineNumber, pos.column, pos.lineNumber, pos.column),
        text: closing, forceMoveMarkers: false
      }]);
      editor.setPosition(pos);                             // cursor entre <tag> y </tag>
    });
  }

  function createModelUri(monaco, path) {
    var normalized = normalizeRelativePath(path);
    return monaco.Uri.from({
      scheme: 'geram-workspace',
      authority: 'local',
      path: '/' + normalized
    });
  }

  function dispatchWindowEvent(windowObject, name, detail) {
    if (!windowObject || typeof windowObject.dispatchEvent !== 'function') { return; }
    var EventConstructor = windowObject.CustomEvent;
    if (typeof EventConstructor !== 'function') { return; }
    windowObject.dispatchEvent(new EventConstructor(name, { detail: detail }));
  }

  function modelLanguage(model, path) {
    return model && typeof model.getLanguageId === 'function' ? model.getLanguageId() : languageForPath(path);
  }

  function pathFromWorkspaceUri(uri) {
    if (!uri) { return ''; }
    var scheme = uri.scheme || (uri.parts && uri.parts.scheme);
    var authority = uri.authority || (uri.parts && uri.parts.authority);
    var path = uri.path || (uri.parts && uri.parts.path);
    if (scheme !== 'geram-workspace' || authority !== 'local' || typeof path !== 'string') { return ''; }
    try { return normalizeRelativePath(path.replace(/^\//, '')); }
    catch (e) { return ''; }
  }

  function configureMonacoEnvironment(windowObject) {
    var previous = windowObject.MonacoEnvironment || {};
    windowObject.MonacoEnvironment = {
      baseUrl: MONACO_BASE + '/',
      createTrustedTypesPolicy: previous.createTrustedTypesPolicy,
      getWorkerUrl: function() { return WORKER_BOOTSTRAP; }
    };
  }

  function MonacoLoader() {
    this.promise = null;
  }

  MonacoLoader.prototype.load = function(windowObject) {
    if (windowObject.monaco && windowObject.monaco.editor) {
      return Promise.resolve(windowObject.monaco);
    }
    if (this.promise) { return this.promise; }

    var amdRequire = windowObject.require;
    if (typeof amdRequire !== 'function' || typeof amdRequire.config !== 'function') {
      return Promise.reject(new Error('monaco_loader_unavailable'));
    }

    configureMonacoEnvironment(windowObject);
    amdRequire.config({
      paths: { vs: MONACO_BASE },
      preferScriptTags: true
    });
    this.promise = new Promise(function(resolve, reject) {
      amdRequire(['vs/editor/editor.main'], function() {
        if (windowObject.monaco && windowObject.monaco.editor) {
          resolve(windowObject.monaco);
        } else {
          reject(new Error('monaco_global_unavailable'));
        }
      }, function() {
        reject(new Error('monaco_load_failed'));
      });
    });
    return this.promise;
  };

  function createResizeSubscription(windowObject, container, layout) {
    if (typeof windowObject.ResizeObserver === 'function') {
      var observer = new windowObject.ResizeObserver(layout);
      observer.observe(container);
      return { dispose: function() { observer.disconnect(); } };
    }
    windowObject.addEventListener('resize', layout);
    return {
      dispose: function() { windowObject.removeEventListener('resize', layout); }
    };
  }

  function MonacoEditorAdapter(monaco, options) {
    this.monaco = monaco;
    this.container = options.container;
    this.windowObject = options.windowObject;
    this.onChange = options.onChange || function() {};
    this.onSave = options.onSave || function() {};
    this.models = new Map();
    this.activePath = '';
    this.destroyed = false;
    defineGeramTheme(monaco);
    configureLanguageDefaults(monaco);
    // emmet-monaco-es enlaza providers globales y exige registrarlos antes de
    // crear cualquier instancia del editor. Hacerlo después deja su tokenizer
    // interno sin estado y rompe el ciclo de sugerencias.
    registerEmmet(monaco, this.windowObject);
    this.editor = monaco.editor.create(this.container, {
      model: null,
      readOnly: true,
      automaticLayout: false,
      theme: options.lightTheme ? 'vs' : 'geram-neon',
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
      fontSize: 13,
      fontLigatures: true,
      lineHeight: 20,
      minimap: { enabled: true, renderCharacters: true, maxColumn: 120 },
      renderLineHighlight: 'all',
      smoothScrolling: true,
      cursorBlinking: 'smooth',
      roundedSelection: true,
      scrollBeyondLastLine: false,
      tabSize: 4,
      insertSpaces: true,
      wordWrap: 'off',
      accessibilitySupport: 'auto',
      // --- Autocompletado / IntelliSense y ayudas de escritura (v3) ---
      // Los language workers de Monaco (css/html/json/typescript) están
      // vendorizados localmente, así que IntelliSense corre offline.
      autoClosingBrackets: 'always',
      autoClosingQuotes: 'always',
      autoClosingOvertype: 'always',
      autoSurround: 'languageDefined',
      autoIndent: 'full',
      formatOnType: true,
      formatOnPaste: true,
      quickSuggestions: { other: true, comments: false, strings: true },
      suggestOnTriggerCharacters: true,
      acceptSuggestionOnEnter: 'on',
      tabCompletion: 'on',
      wordBasedSuggestions: 'currentDocument',
      parameterHints: { enabled: true },
      snippetSuggestions: 'inline',
      suggest: { showWords: true, preview: true, insertMode: 'insert' },
      bracketPairColorization: { enabled: true },
      matchBrackets: 'always'
    });

    installAutoCloseTags(monaco, this);

    this.editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
      this.onSave
    );
    var editor = this.editor;
    function runEditorAction(actionId) {
      if (typeof editor.getAction !== 'function') { return; }
      var action = editor.getAction(actionId);
      if (action && typeof action.run === 'function') { action.run(); }
    }
    if (monaco.KeyCode.Space !== undefined) {
      this.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Space, function() {
        runEditorAction('editor.action.triggerSuggest');
      });
    }
    if (monaco.KeyCode.F12 !== undefined) {
      this.editor.addCommand(monaco.KeyCode.F12, function() {
        runEditorAction('editor.action.revealDefinition');
      });
      this.editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.F12, function() {
        runEditorAction('editor.action.goToReferences');
      });
    }
    if (monaco.KeyCode.F2 !== undefined) {
      this.editor.addCommand(monaco.KeyCode.F2, function() {
        runEditorAction('editor.action.rename');
      });
    }
    var adapterInstance = this;
    this.markerSubscription = monaco.editor.onDidChangeMarkers ?
      monaco.editor.onDidChangeMarkers(function() { adapterInstance.publishProblems(); }) : null;
    this.resizeSubscription = createResizeSubscription(
      this.windowObject,
      this.container,
      this.layout.bind(this)
    );
  }

  MonacoEditorAdapter.prototype.openDocument = function(documentState) {
    var path = normalizeRelativePath(documentState.path);
    var record = this.models.get(path);
    if (!record) {
      var uri = createModelUri(this.monaco, path);
      var model = this.monaco.editor.getModel(uri);
      var created = !model;
      if (!model) {
        model = this.monaco.editor.createModel(
          String(documentState.currentContent),
          languageForPath(path),
          uri
        );
      }
      record = {
        model: model,
        owned: created,
        savedContent: String(documentState.savedContent),
        suppressChanges: 0,
        changeSubscription: null
      };
      if (!created) {
        record.suppressChanges += 1;
        model.setValue(String(documentState.currentContent));
        record.suppressChanges -= 1;
      }
      var adapter = this;
      record.changeSubscription = model.onDidChangeContent(function() {
        if (record.suppressChanges) { return; }
        var content = model.getValue();
        adapter.onChange(path, content, content !== record.savedContent);
        dispatchWindowEvent(adapter.windowObject, 'geram:model-change', {
          path: path, language: modelLanguage(model, path), content: content
        });
      });
      this.models.set(path, record);
    }

    this.activePath = path;
    this.monaco.editor.setModelLanguage(record.model, languageForPath(path));
    this.editor.setModel(record.model);
    this.editor.updateOptions({ readOnly: false });
    this.publishProblems();
    dispatchWindowEvent(this.windowObject, 'geram:model-open', {
      path: path, language: modelLanguage(record.model, path), content: record.model.getValue()
    });
    return record.model;
  };

  MonacoEditorAdapter.prototype.publishProblems = function() {
    if (!this.monaco.editor.getModelMarkers) { return; }
    var problems = [];
    this.models.forEach(function(record) {
      var path = pathFromWorkspaceUri(record.model.uri);
      if (!path) { return; }
      var markers = this.monaco.editor.getModelMarkers({ resource: record.model.uri }) || [];
      markers.forEach(function(marker) {
        if (marker.severity !== 8 && marker.severity !== 4) { return; }
        if (String(marker.source || '').toLowerCase() === 'pyright') { return; }
        problems.push({
          path: path,
          severity: marker.severity,
          message: String(marker.message || 'Diagnostic without a message.'),
          source: typeof marker.source === 'string' ? marker.source : '',
          line: Number(marker.startLineNumber) || 1,
          column: Number(marker.startColumn) || 1
        });
      });
    }, this);
    problems.sort(function(left, right) {
      return right.severity - left.severity || left.path.localeCompare(right.path) ||
        left.line - right.line || left.column - right.column;
    });
    dispatchWindowEvent(this.windowObject, 'geram:problems', { problems: problems });
  };

  MonacoEditorAdapter.prototype.revealLocation = function(path, line, column) {
    var record = this.models.get(normalizeRelativePath(path));
    if (!record) { return false; }
    this.activePath = normalizeRelativePath(path);
    this.editor.setModel(record.model);
    var position = { lineNumber: Math.max(1, Number(line) || 1), column: Math.max(1, Number(column) || 1) };
    if (typeof this.editor.setPosition === 'function') { this.editor.setPosition(position); }
    if (typeof this.editor.revealPositionInCenter === 'function') { this.editor.revealPositionInCenter(position); }
    this.editor.focus();
    return true;
  };

  MonacoEditorAdapter.prototype.getContent = function(path) {
    var target = path ? normalizeRelativePath(path) : this.activePath;
    var record = this.models.get(target);
    return record ? record.model.getValue() : '';
  };

  MonacoEditorAdapter.prototype.setContent = function(content, options) {
    var target = options && options.path ? normalizeRelativePath(options.path) : this.activePath;
    var record = this.models.get(target);
    if (!record) { return; }
    record.suppressChanges += 1;
    record.model.setValue(String(content));
    record.suppressChanges -= 1;
    if (options && options.saved) { record.savedContent = String(content); }
  };

  MonacoEditorAdapter.prototype.isModified = function(path) {
    var target = path ? normalizeRelativePath(path) : this.activePath;
    var record = this.models.get(target);
    return Boolean(record && record.model.getValue() !== record.savedContent);
  };

  MonacoEditorAdapter.prototype.markSaved = function(path, content) {
    var record = this.models.get(normalizeRelativePath(path));
    if (record) {
      record.savedContent = String(content);
      dispatchWindowEvent(this.windowObject, 'geram:model-save', {
        path: normalizeRelativePath(path), language: modelLanguage(record.model, path), content: String(content)
      });
    }
  };

  MonacoEditorAdapter.prototype._disposePath = function(path) {
    var target = normalizeRelativePath(path);
    var record = this.models.get(target);
    var uri = createModelUri(this.monaco, target);
    var model = record ? record.model : this.monaco.editor.getModel(uri);
    if (!model) { return; }
    dispatchWindowEvent(this.windowObject, 'geram:model-close', {
      path: target, language: modelLanguage(model, target)
    });
    if (typeof this.monaco.editor.setModelMarkers === 'function') {
      this.monaco.editor.setModelMarkers(model, 'pyright', []);
      this.monaco.editor.setModelMarkers(model, 'javascript', []);
      this.monaco.editor.setModelMarkers(model, 'typescript', []);
    }
    if (record && record.changeSubscription) { record.changeSubscription.dispose(); }
    this.models.delete(target);
    if (typeof model.dispose === 'function') { model.dispose(); }
  };

  MonacoEditorAdapter.prototype.closeDocuments = function(paths) {
    var activeRemoved = paths.indexOf(this.activePath) >= 0;
    paths.forEach(this._disposePath.bind(this));
    if (activeRemoved) {
      this.activePath = '';
      this.editor.setModel(null);
      this.editor.updateOptions({ readOnly: true });
    }
    this.publishProblems();
  };

  MonacoEditorAdapter.prototype.remapDocuments = function(mappings, activePath) {
    var activeMapping = mappings.find(function(mapping) { return mapping.oldPath === this.activePath; }, this);
    var position = activeMapping && this.editor.getPosition ? this.editor.getPosition() : null;
    mappings.forEach(function(mapping) { this._disposePath(mapping.oldPath); }, this);
    mappings.forEach(function(mapping) {
      if (mapping.newPath !== activePath) { this.openDocument(mapping.documentState); }
    }, this);
    var active = mappings.find(function(mapping) { return mapping.newPath === activePath; });
    if (active) {
      this.openDocument(active.documentState);
      if (position && this.editor.setPosition) { this.editor.setPosition(position); }
    }
    this.publishProblems();
  };

  MonacoEditorAdapter.prototype.setReadOnly = function(readOnly) {
    this.editor.updateOptions({ readOnly: Boolean(readOnly) });
  };

  MonacoEditorAdapter.prototype.focus = function() {
    this.editor.focus();
  };

  MonacoEditorAdapter.prototype.setLanguage = function(path) {
    var target = normalizeRelativePath(path);
    var record = this.models.get(target);
    if (record) {
      this.monaco.editor.setModelLanguage(record.model, languageForPath(target));
    }
  };

  MonacoEditorAdapter.prototype.setTheme = function(lightTheme) {
    this.monaco.editor.setTheme(lightTheme ? 'vs' : 'geram-neon');
  };

  MonacoEditorAdapter.prototype.layout = function() {
    if (!this.destroyed) { this.editor.layout(); }
  };

  MonacoEditorAdapter.prototype.destroy = function() {
    if (this.destroyed) { return; }
    this.destroyed = true;
    this.resizeSubscription.dispose();
    if (this.markerSubscription) { this.markerSubscription.dispose(); }
    this.editor.dispose();
    this.models.forEach(function(record) {
      dispatchWindowEvent(this.windowObject, 'geram:model-close', {
        path: pathFromWorkspaceUri(record.model.uri), language: modelLanguage(record.model, pathFromWorkspaceUri(record.model.uri))
      });
      record.changeSubscription.dispose();
      if (record.owned) { record.model.dispose(); }
    }, this);
    this.models.clear();
    this.activePath = '';
  };

  function TextareaEditorAdapter(options) {
    this.textarea = options.textarea;
    this.container = options.container;
    this.onChange = options.onChange || function() {};
    this.onSave = options.onSave || function() {};
    this.models = new Map();
    this.activePath = '';
    this.destroyed = false;
    this.container.hidden = true;
    this.textarea.hidden = false;
    this.textarea.disabled = true;
    var adapter = this;
    this.inputListener = function() {
      var record = adapter.models.get(adapter.activePath);
      if (!record) { return; }
      record.content = adapter.textarea.value;
      adapter.onChange(adapter.activePath, record.content, record.content !== record.savedContent);
    };
    this.keyListener = function(event) {
      if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 's') {
        event.preventDefault();
        adapter.onSave();
      }
    };
    this.textarea.addEventListener('input', this.inputListener);
    this.textarea.addEventListener('keydown', this.keyListener);
  }

  TextareaEditorAdapter.prototype.openDocument = function(documentState) {
    var path = normalizeRelativePath(documentState.path);
    var record = this.models.get(path);
    if (!record) {
      record = {
        content: String(documentState.currentContent),
        savedContent: String(documentState.savedContent)
      };
      this.models.set(path, record);
    }
    this.activePath = path;
    this.textarea.value = record.content;
    this.textarea.disabled = false;
    return record;
  };

  TextareaEditorAdapter.prototype.getContent = function(path) {
    var target = path ? normalizeRelativePath(path) : this.activePath;
    var record = this.models.get(target);
    return record ? record.content : '';
  };

  TextareaEditorAdapter.prototype.closeDocuments = function(paths) {
    paths.forEach(function(path) { this.models.delete(normalizeRelativePath(path)); }, this);
    if (paths.indexOf(this.activePath) >= 0) {
      this.activePath = ''; this.textarea.value = ''; this.textarea.disabled = true;
    }
  };

  TextareaEditorAdapter.prototype.remapDocuments = function(mappings, activePath) {
    mappings.forEach(function(mapping) {
      var record = this.models.get(mapping.oldPath);
      this.models.delete(mapping.oldPath);
      if (record) { this.models.set(mapping.newPath, record); }
    }, this);
    this.activePath = activePath || '';
    var active = this.models.get(this.activePath);
    this.textarea.value = active ? active.content : '';
  };

  TextareaEditorAdapter.prototype.setContent = function(content, options) {
    var target = options && options.path ? normalizeRelativePath(options.path) : this.activePath;
    var record = this.models.get(target);
    if (!record) { return; }
    record.content = String(content);
    if (options && options.saved) { record.savedContent = record.content; }
    if (target === this.activePath) { this.textarea.value = record.content; }
  };

  TextareaEditorAdapter.prototype.isModified = function(path) {
    var target = path ? normalizeRelativePath(path) : this.activePath;
    var record = this.models.get(target);
    return Boolean(record && record.content !== record.savedContent);
  };

  TextareaEditorAdapter.prototype.markSaved = function(path, content) {
    var record = this.models.get(normalizeRelativePath(path));
    if (record) { record.savedContent = String(content); }
  };

  TextareaEditorAdapter.prototype.setReadOnly = function(readOnly) {
    this.textarea.disabled = Boolean(readOnly);
  };
  TextareaEditorAdapter.prototype.focus = function() { this.textarea.focus(); };
  TextareaEditorAdapter.prototype.setLanguage = function() {};
  TextareaEditorAdapter.prototype.setTheme = function() {};
  TextareaEditorAdapter.prototype.layout = function() {};
  TextareaEditorAdapter.prototype.destroy = function() {
    if (this.destroyed) { return; }
    this.destroyed = true;
    this.textarea.removeEventListener('input', this.inputListener);
    this.textarea.removeEventListener('keydown', this.keyListener);
    this.models.clear();
    this.activePath = '';
  };

  var defaultLoader = new MonacoLoader();

  function initializeEditor(options) {
    var loader = options.loader || defaultLoader;
    options.loadingElement.hidden = false;
    options.container.hidden = false;
    options.textarea.hidden = true;
    return loader.load(options.windowObject).then(function(monaco) {
      var adapter = new MonacoEditorAdapter(monaco, options);
      options.loadingElement.hidden = true;
      return { adapter: adapter, fallback: false, errorCode: '' };
    }).catch(function() {
      var fallback = new TextareaEditorAdapter(options);
      options.loadingElement.hidden = true;
      if (typeof options.onFallback === 'function') {
        options.onFallback('monaco_load_failed');
      }
      return { adapter: fallback, fallback: true, errorCode: 'monaco_load_failed' };
    });
  }

  return {
    MONACO_BASE: MONACO_BASE,
    WORKER_BOOTSTRAP: WORKER_BOOTSTRAP,
    MonacoEditorAdapter: MonacoEditorAdapter,
    MonacoLoader: MonacoLoader,
    TextareaEditorAdapter: TextareaEditorAdapter,
    configureMonacoEnvironment: configureMonacoEnvironment,
    createModelUri: createModelUri,
    pathFromWorkspaceUri: pathFromWorkspaceUri,
    initializeEditor: initializeEditor,
    closingTagForContext: closingTagForContext,
    languageForPath: languageForPath,
    normalizeRelativePath: normalizeRelativePath
  };
});
