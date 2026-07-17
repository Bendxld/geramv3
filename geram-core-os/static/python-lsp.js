(function(root, factory) {
  'use strict';
  var exported = factory();
  if (typeof module === 'object' && module.exports) { module.exports = exported; }
  if (root && root.document) { exported.initialize(root); }
})(typeof window !== 'undefined' ? window : null, function() {
  'use strict';

  function lspPosition(position) {
    return { line: Math.max(0, position.lineNumber - 1), character: Math.max(0, position.column - 1) };
  }
  function monacoRange(range) {
    return {
      startLineNumber: range.start.line + 1, startColumn: range.start.character + 1,
      endLineNumber: range.end.line + 1, endColumn: range.end.character + 1
    };
  }
  function relativeFromUri(uri) {
    var prefix = 'file:///workspace/';
    if (typeof uri !== 'string' || uri.indexOf(prefix) !== 0) { return ''; }
    var path = uri.slice(prefix.length);
    return path && path.indexOf('..') === -1 && path.indexOf('\\') === -1 ? path : '';
  }
  function markup(value) {
    if (typeof value === 'string') { return { value: value }; }
    if (value && typeof value.value === 'string') { return { value: value.value }; }
    if (Array.isArray(value)) { return value.map(markup); }
    return { value: '' };
  }
  function completionKind(value) {
    var numeric = Number(value);
    return numeric >= 1 && numeric <= 25 ? numeric - 1 : 18;
  }
  function symbol(value) {
    if (!value || typeof value.name !== 'string' || !value.range || !value.selectionRange) { return null; }
    var converted = {
      name: value.name,
      detail: typeof value.detail === 'string' ? value.detail : '',
      kind: Math.max(0, Number(value.kind || 1) - 1),
      range: monacoRange(value.range),
      selectionRange: monacoRange(value.selectionRange),
      tags: value.tags
    };
    if (Array.isArray(value.children)) { converted.children = value.children.map(symbol).filter(Boolean); }
    return converted;
  }

  function PythonLspClient(windowObject, controller, monaco) {
    this.windowObject = windowObject;
    this.controller = controller;
    this.monaco = monaco;
    this.socket = null;
    this.ready = false;
    this.queue = [];
    this.pending = new Map();
    this.nextId = 0;
    this.versions = new Map();
    this.diagnostics = new Map();
    this.changeTimers = new Map();
    this.disposables = [];
    this.destroyed = false;
    this.retryTimer = null;
  }

  PythonLspClient.prototype.connect = function() {
    var protocol = this.windowObject.location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.socket = new this.windowObject.WebSocket(protocol + '//' + this.windowObject.location.host + '/ws/python-lsp');
    var client = this;
    this.socket.addEventListener('open', function() {});
    this.socket.addEventListener('message', function(event) {
      var message;
      try { message = JSON.parse(event.data); } catch (error) { return; }
      if (message.type === 'status') {
        client.ready = message.status === 'ready';
        if (client.ready) { client.flush(); client.openExistingModels(); }
        else if (message.status === 'unavailable' && client.socket) { client.socket.close(); }
      } else if (message.type === 'response' || message.type === 'error') {
        var pending = client.pending.get(message.request_id);
        if (pending) {
          client.pending.delete(message.request_id);
          if (message.type === 'error') { pending.reject(new Error(message.code || 'python_lsp_error')); }
          else { pending.resolve(message.result); }
        }
      } else if (message.type === 'diagnostics') {
        client.updateDiagnostics(message.path, message.diagnostics);
      }
    });
    this.socket.addEventListener('close', function() {
      client.ready = false;
      client.pending.forEach(function(pending) { pending.reject(new Error('python_lsp_unavailable')); });
      client.pending.clear();
      client.queue = [];
      client.changeTimers.forEach(function(timer) { client.windowObject.clearTimeout(timer); });
      client.changeTimers.clear();
      client.versions.clear();
      if (!client.destroyed) {
        client.retryTimer = client.windowObject.setTimeout(function() { client.connect(); }, 1000);
      }
    });
  };

  PythonLspClient.prototype.send = function(message) {
    if (!this.ready || !this.socket || this.socket.readyState !== 1) { this.queue.push(message); return; }
    this.socket.send(JSON.stringify(message));
  };
  PythonLspClient.prototype.flush = function() {
    while (this.queue.length && this.ready) { this.socket.send(JSON.stringify(this.queue.shift())); }
  };
  PythonLspClient.prototype.request = function(method, model, position, extra) {
    var client = this;
    var runtime = this.windowObject;
    var requestId = 'python-' + String(++this.nextId);
    var payload = { type: 'request', request_id: requestId, method: method };
    if (model) { payload.path = relativeFromUri(model.uri.toString().replace('geram-workspace://local/', 'file:///workspace/')); }
    if (position) { payload.position = lspPosition(position); }
    Object.keys(extra || {}).forEach(function(key) { payload[key] = extra[key]; });
    return new Promise(function(resolve, reject) {
      var timeout = runtime.setTimeout(function() {
        client.pending.delete(requestId); reject(new Error('python_lsp_timeout'));
      }, 9000);
      client.pending.set(requestId, {
        resolve: function(value) { runtime.clearTimeout(timeout); resolve(value); },
        reject: function(error) { runtime.clearTimeout(timeout); reject(error); }
      });
      client.send(payload);
    });
  };

  PythonLspClient.prototype.workspaceSymbols = function(query) {
    return this.request('workspace/symbol', null, null, { query: String(query || '').slice(0, 128) });
  };

  PythonLspClient.prototype.modelEvent = function(type, detail) {
    if (!detail || detail.language !== 'python' || typeof detail.path !== 'string') { return; }
    var version = this.versions.get(detail.path) || 0;
    if (type === 'open') {
      if (version) { return; }
      version = 1; this.versions.set(detail.path, version);
      this.send({ type: 'open', path: detail.path, version: version, text: detail.content || '' });
    } else if (type === 'change') {
      version += 1; this.versions.set(detail.path, version);
      var client = this;
      if (this.changeTimers.has(detail.path)) { this.windowObject.clearTimeout(this.changeTimers.get(detail.path)); }
      this.changeTimers.set(detail.path, this.windowObject.setTimeout(function() {
        client.send({ type: 'change', path: detail.path, version: version, text: detail.content || '' });
        client.changeTimers.delete(detail.path);
      }, 80));
    } else if (type === 'save') {
      if (this.changeTimers.has(detail.path)) {
        this.windowObject.clearTimeout(this.changeTimers.get(detail.path));
        this.changeTimers.delete(detail.path);
        this.send({ type: 'change', path: detail.path, version: version, text: detail.content || '' });
      }
      this.send({ type: 'save', path: detail.path, text: detail.content || '' });
    } else if (type === 'close') {
      if (this.changeTimers.has(detail.path)) {
        this.windowObject.clearTimeout(this.changeTimers.get(detail.path));
        this.changeTimers.delete(detail.path);
      }
      this.send({ type: 'close', path: detail.path });
      this.versions.delete(detail.path);
      this.diagnostics.delete(detail.path);
      var all = [];
      this.diagnostics.forEach(function(items) { all = all.concat(items); });
      this.windowObject.dispatchEvent(new this.windowObject.CustomEvent('geram:python-problems', { detail: { problems: all } }));
    }
  };

  PythonLspClient.prototype.openExistingModels = function() {
    var client = this;
    this.controller.editorReady.then(function(adapter) {
      adapter.models.forEach(function(record, path) {
        if (record.model.getLanguageId() === 'python') {
          client.modelEvent('open', { path: path, language: 'python', content: record.model.getValue() });
        }
      });
    });
  };

  PythonLspClient.prototype.updateDiagnostics = function(path, diagnostics) {
    var raw = Array.isArray(diagnostics) ? diagnostics : [];
    var modelUri = this.monaco.Uri.from({ scheme: 'geram-workspace', authority: 'local', path: '/' + path });
    var model = this.monaco.editor.getModel(modelUri);
    if (model && typeof this.monaco.editor.setModelMarkers === 'function') {
      this.monaco.editor.setModelMarkers(model, 'pyright', raw.filter(function(item) {
        return item && item.range;
      }).map(function(item) {
        var range = monacoRange(item.range);
        return {
          severity: item.severity === 1 ? 8 : (item.severity === 2 ? 4 : 2),
          message: String(item.message || 'Python diagnostic.'),
          source: 'pyright', code: item.code,
          startLineNumber: range.startLineNumber, startColumn: range.startColumn,
          endLineNumber: range.endLineNumber, endColumn: range.endColumn
        };
      }));
    }
    var mapped = raw.filter(function(item) {
      return item && (item.severity === 1 || item.severity === 2) && item.range;
    }).map(function(item) {
      return {
        path: path, severity: item.severity === 1 ? 8 : 4,
        message: String(item.message || 'Python diagnostic.'), source: 'pyright',
        line: item.range.start.line + 1, column: item.range.start.character + 1
      };
    });
    this.diagnostics.set(path, mapped);
    var all = [];
    this.diagnostics.forEach(function(items) { all = all.concat(items); });
    this.windowObject.dispatchEvent(new this.windowObject.CustomEvent('geram:python-problems', { detail: { problems: all } }));
  };

  PythonLspClient.prototype.location = function(value) {
    var client = this;
    var values = Array.isArray(value) ? value : (value ? [value] : []);
    return values.map(function(item) {
      var path = relativeFromUri(item.uri || item.targetUri);
      var range = item.range || item.targetSelectionRange || item.targetRange;
      if (!path || !range) { return null; }
      var uri = client.monaco.Uri.from({ scheme: 'geram-workspace', authority: 'local', path: '/' + path });
      return { uri: uri, range: monacoRange(range) };
    }).filter(Boolean);
  };

  PythonLspClient.prototype.ensureLocations = function(value) {
    var client = this;
    var locations = this.location(value);
    return Promise.all(locations.map(function(location) {
      if (client.monaco.editor.getModel(location.uri)) { return location; }
      var path = relativeFromUri(location.uri.toString().replace('geram-workspace://local/', 'file:///workspace/'));
      if (!path || typeof client.windowObject.fetch !== 'function') { return location; }
      return client.windowObject.fetch('/api/workspace/file?path=' + encodeURIComponent(path), {
        method: 'GET', credentials: 'same-origin'
      }).then(function(response) {
        if (!response.ok) { return location; }
        return response.json().then(function(file) {
          if (!file || file.path !== path || typeof file.content !== 'string') { return location; }
          if (!client.monaco.editor.getModel(location.uri)) {
            client.monaco.editor.createModel(file.content, 'python', location.uri);
            client.modelEvent('open', { path: path, language: 'python', content: file.content });
          }
          return location;
        });
      }).catch(function() { return location; });
    }));
  };

  PythonLspClient.prototype.registerProviders = function() {
    var client = this, languages = this.monaco.languages;
    this.disposables.push(languages.registerCompletionItemProvider('python', {
      triggerCharacters: ['.'], provideCompletionItems: function(model, position) {
        return client.request('textDocument/completion', model, position).then(function(result) {
          var items = Array.isArray(result) ? result : (result && result.items) || [];
          return { suggestions: items.map(function(item) {
            var suggestion = { label: item.label, kind: completionKind(item.kind), detail: item.detail, insertText: item.insertText || item.label };
            if (item.documentation) { suggestion.documentation = markup(item.documentation); }
            if (item.textEdit && item.textEdit.range) { suggestion.range = monacoRange(item.textEdit.range); suggestion.insertText = item.textEdit.newText; }
            if (item.insertTextFormat === 2) { suggestion.insertTextRules = 4; }
            if (Array.isArray(item.additionalTextEdits)) {
              suggestion.additionalTextEdits = item.additionalTextEdits.map(function(edit) {
                return { range: monacoRange(edit.range), text: edit.newText };
              });
            }
            return suggestion;
          }) };
        }).catch(function() { return { suggestions: [] }; });
      }
    }));
    this.disposables.push(languages.registerHoverProvider('python', { provideHover: function(model, position) {
      return client.request('textDocument/hover', model, position).then(function(result) {
        return result ? { contents: Array.isArray(result.contents) ? result.contents.map(markup) : [markup(result.contents)], range: result.range ? monacoRange(result.range) : undefined } : null;
      }).catch(function() { return null; });
    }}));
    this.disposables.push(languages.registerSignatureHelpProvider('python', {
      signatureHelpTriggerCharacters: ['(', ','], provideSignatureHelp: function(model, position) {
        return client.request('textDocument/signatureHelp', model, position).then(function(result) {
          if (!result) { return null; }
          return { value: result, dispose: function() {} };
        }).catch(function() { return null; });
      }
    }));
    this.disposables.push(languages.registerDefinitionProvider('python', { provideDefinition: function(model, position) {
      return client.request('textDocument/definition', model, position).then(client.ensureLocations.bind(client)).catch(function() { return []; });
    }}));
    this.disposables.push(languages.registerReferenceProvider('python', { provideReferences: function(model, position) {
      return client.request('textDocument/references', model, position).then(client.ensureLocations.bind(client)).catch(function() { return []; });
    }}));
    this.disposables.push(languages.registerRenameProvider('python', { provideRenameEdits: function(model, position, newName) {
      return client.request('textDocument/rename', model, position, { new_name: newName }).then(function(result) {
        var edits = [];
        Object.keys((result && result.changes) || {}).forEach(function(uri) {
          var path = relativeFromUri(uri);
          if (!path) { return; }
          var resource = client.monaco.Uri.from({ scheme: 'geram-workspace', authority: 'local', path: '/' + path });
          result.changes[uri].forEach(function(edit) { edits.push({ resource: resource, textEdit: { range: monacoRange(edit.range), text: edit.newText } }); });
        });
        ((result && result.documentChanges) || []).forEach(function(change) {
          var path = relativeFromUri(change && change.textDocument && change.textDocument.uri);
          if (!path || !Array.isArray(change.edits)) { return; }
          var resource = client.monaco.Uri.from({ scheme: 'geram-workspace', authority: 'local', path: '/' + path });
          change.edits.forEach(function(edit) {
            edits.push({ resource: resource, textEdit: { range: monacoRange(edit.range), text: edit.newText } });
          });
        });
        return { edits: edits };
      }).catch(function() { return { edits: [] }; });
    }}));
    this.disposables.push(languages.registerDocumentSymbolProvider('python', { provideDocumentSymbols: function(model) {
      return client.request('textDocument/documentSymbol', model).then(function(result) {
        return (Array.isArray(result) ? result : []).map(symbol).filter(Boolean);
      }).catch(function() { return []; });
    }}));
  };

  PythonLspClient.prototype.destroy = function() {
    this.destroyed = true;
    if (this.retryTimer) { this.windowObject.clearTimeout(this.retryTimer); }
    this.disposables.forEach(function(item) { if (item && item.dispose) { item.dispose(); } });
    if (this.socket) { this.socket.close(); }
  };

  function initialize(windowObject) {
    var controller = windowObject.GeramWorkspaceController;
    if (!controller || !controller.editorReady) { return null; }
    var client;
    controller.editorReady.then(function(adapter) {
      if (!adapter.monaco) { return; }
      client = new PythonLspClient(windowObject, controller, adapter.monaco);
      client.registerProviders(); client.connect();
      ['open', 'change', 'save', 'close'].forEach(function(type) {
        windowObject.addEventListener('geram:model-' + type, function(event) { client.modelEvent(type, event.detail); });
      });
      windowObject.addEventListener('beforeunload', function() { client.destroy(); }, { once: true });
      windowObject.GeramPythonLsp = client;
    });
    return client;
  }

  return {
    PythonLspClient: PythonLspClient, initialize: initialize,
    lspPosition: lspPosition, monacoRange: monacoRange,
    relativeFromUri: relativeFromUri, symbol: symbol
  };
});
