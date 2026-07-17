(function(root, factory) {
  'use strict';
  var exported = factory();
  if (typeof module === 'object' && module.exports) { module.exports = exported; }
  if (root && root.document) { exported.initialize(root, root.document); }
})(typeof window !== 'undefined' ? window : null, function() {
  'use strict';

  function fuzzyScore(query, path) {
    var needle = String(query || '').toLowerCase().trim();
    var haystack = String(path || '').toLowerCase();
    if (!needle) { return 0; }
    var positions = [], start = 0;
    for (var i = 0; i < needle.length; i += 1) {
      var index = haystack.indexOf(needle[i], start);
      if (index < 0) { return null; }
      positions.push(index); start = index + 1;
    }
    var basename = haystack.split('/').pop();
    var bonus = basename.indexOf(needle) === 0 ? -100 : (basename.indexOf(needle) >= 0 ? -50 : 0);
    return (positions[positions.length - 1] - positions[0] + 1) * 4 + positions[0] + haystack.length + bonus;
  }

  function filters(value) {
    return String(value || '').split(',').map(function(item) { return item.trim(); }).filter(Boolean).slice(0, 16);
  }

  function NavigationHistory(limit) {
    this.limit = limit || 100; this.entries = []; this.index = -1;
  }
  NavigationHistory.prototype.push = function(location) {
    if (!location || !location.path) { return; }
    var current = this.entries[this.index];
    if (current && current.path === location.path && current.line === location.line && current.column === location.column) { return; }
    this.entries = this.entries.slice(0, this.index + 1);
    this.entries.push(location);
    if (this.entries.length > this.limit) { this.entries.shift(); }
    this.index = this.entries.length - 1;
  };
  NavigationHistory.prototype.back = function() {
    if (this.index <= 0) { return null; }
    this.index -= 1; return this.entries[this.index];
  };
  NavigationHistory.prototype.forward = function() {
    if (this.index >= this.entries.length - 1) { return null; }
    this.index += 1; return this.entries[this.index];
  };
  NavigationHistory.prototype.remap = function(oldPath, newPath, itemType) {
    var prefix = oldPath + '/';
    this.entries.forEach(function(location) {
      if (location.path === oldPath) { location.path = newPath; }
      else if (itemType === 'directory' && location.path.indexOf(prefix) === 0) { location.path = newPath + location.path.slice(oldPath.length); }
    });
  };
  NavigationHistory.prototype.remove = function(path, itemType) {
    var prefix = path + '/';
    this.entries = this.entries.filter(function(location) {
      return location.path !== path && !(itemType === 'directory' && location.path.indexOf(prefix) === 0);
    });
    this.index = Math.min(this.index, this.entries.length - 1);
  };

  function apiError(response) {
    return response.json().then(function(payload) {
      var detail = payload && payload.detail;
      throw new Error(detail && detail.code || 'navigation_failed');
    }).catch(function(error) { throw error instanceof Error ? error : new Error('navigation_failed'); });
  }
  function jsonFetch(windowObject, url, options) {
    return windowObject.fetch(url, Object.assign({ credentials: 'same-origin', cache: 'no-store' }, options || {})).then(function(response) {
      if (!response.ok) { return apiError(response); }
      return response.json();
    });
  }

  function initialize(windowObject, documentObject) {
    var controller = windowObject.GeramWorkspaceController;
    var dialog = documentObject.getElementById('workspaceNavigation');
    if (!controller || !dialog) { return null; }
    var input = documentObject.getElementById('workspaceNavigationInput');
    var title = documentObject.getElementById('workspaceNavigationTitle');
    var results = documentObject.getElementById('workspaceNavigationResults');
    var status = documentObject.getElementById('workspaceNavigationStatus');
    var searchOptions = documentObject.getElementById('workspaceSearchOptions');
    var replacementRow = documentObject.getElementById('workspaceReplacementRow');
    var replacementInput = documentObject.getElementById('workspaceReplacementInput');
    var applyButton = documentObject.getElementById('workspaceReplacementApply');
    var runButton = documentObject.getElementById('workspaceSearchRun');
    var cancelButton = documentObject.getElementById('workspaceNavigationCancel');
    var closeButton = documentObject.getElementById('workspaceNavigationClose');
    var mode = 'files', files = [], recent = [], selected = 0, aborter = null, activeJob = '', pollTimer = null, symbolTimer = null, symbolSequence = 0, previewToken = '';
    var history = new NavigationHistory(100);

    function setStatus(message) { status.textContent = message || ''; }
    function clearResults() { while (results.firstChild) { results.removeChild(results.firstChild); } selected = 0; }
    function buttons() { return Array.prototype.slice.call(results.querySelectorAll('button')); }
    function select(index) {
      var items = buttons(); if (!items.length) { return; }
      selected = Math.max(0, Math.min(index, items.length - 1));
      items.forEach(function(item, itemIndex) { item.classList.toggle('selected', itemIndex === selected); });
      items[selected].scrollIntoView({ block: 'nearest' });
    }
    function button(label, meta, action) {
      var element = documentObject.createElement('button'); element.type = 'button'; element.className = 'workspace-navigation-result';
      var main = documentObject.createElement('span'); main.textContent = label;
      var detail = documentObject.createElement('span'); detail.textContent = meta || ''; detail.className = 'workspace-navigation-meta';
      element.appendChild(main); element.appendChild(detail); element.addEventListener('click', action); results.appendChild(element); return element;
    }
    function currentLocation() {
      return controller.editorReady.then(function(adapter) {
        var position = adapter.editor && adapter.editor.getPosition ? adapter.editor.getPosition() : null;
        return { path: controller.activePath(), line: position ? position.lineNumber : 1, column: position ? position.column : 1 };
      });
    }
    function openLocation(location, record) {
      if (!location || !location.path || !controller.state.canOpen(location.path)) { return Promise.resolve(false); }
      var before;
      return currentLocation().then(function(value) {
        before = value;
        if (controller.state.has(location.path)) { return true; }
        return controller.api.read(location.path).then(function(file) { controller.state.load(file); return true; });
      }).then(function(ok) {
        if (!ok) { return false; }
        return controller.navigate(location.path, location.line || 1, location.column || 1);
      }).then(function(ok) {
        if (ok && record !== false) {
          history.push(before); history.push({ path: location.path, line: location.line || 1, column: location.column || 1 });
          recent = [location.path].concat(recent.filter(function(path) { return path !== location.path; })).slice(0, 30);
        }
        if (ok) { close(); }
        return ok;
      }).catch(function() { setStatus('The location could not be opened.'); return false; });
    }
    function renderFiles() {
      clearResults(); var query = input.value;
      var open = new Set(Array.from(controller.state.documents.keys()));
      var ranked = files.map(function(path) {
        var score = fuzzyScore(query, path); if (score === null) { return null; }
        if (open.has(path)) { score -= 1000; }
        var recentIndex = recent.indexOf(path); if (recentIndex >= 0) { score -= 500 - recentIndex; }
        return { path: path, score: score };
      }).filter(Boolean).sort(function(a, b) { return a.score - b.score || a.path.localeCompare(b.path); }).slice(0, 100);
      ranked.forEach(function(item) { button(item.path.split('/').pop(), item.path, function() { openLocation({ path: item.path, line: 1, column: 1 }); }); });
      setStatus(ranked.length ? ranked.length + ' files' : 'No results'); select(0);
    }
    function searchPayload() {
      return {
        query: input.value, case_sensitive: documentObject.getElementById('workspaceSearchCase').checked,
        whole_word: documentObject.getElementById('workspaceSearchWord').checked,
        regex: documentObject.getElementById('workspaceSearchRegex').checked,
        include: filters(documentObject.getElementById('workspaceSearchInclude').value),
        exclude: filters(documentObject.getElementById('workspaceSearchExclude').value), limit: 500
      };
    }
    function renderSearch(payload) {
      clearResults(); var lastPath = '';
      (payload.results || []).forEach(function(result) {
        if (result.path !== lastPath) {
          var heading = documentObject.createElement('li'); heading.className = 'workspace-navigation-group'; heading.textContent = result.path; results.appendChild(heading); lastPath = result.path;
        }
        button(result.preview, result.line + ':' + result.column, function() { openLocation(result); });
      });
      setStatus(payload.results.length + ' matches' + (payload.limited ? ' · limit reached' : ''));
      if (!payload.results.length) { setStatus('No results'); } select(0);
    }
    function runSearch() {
      if (!input.value) { clearResults(); setStatus('Enter text to search for.'); return; }
      if (aborter) { aborter.abort(); }
      aborter = new windowObject.AbortController(); setStatus('Buscando…'); activeJob = '';
      jsonFetch(windowObject, '/api/navigation/search/jobs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(searchPayload()), signal: aborter.signal
      }).then(function(job) {
        activeJob = job.job_id;
        function poll() {
          jsonFetch(windowObject, '/api/navigation/search/jobs/' + encodeURIComponent(activeJob)).then(function(state) {
            if (state.status === 'complete') { activeJob = ''; renderSearch(state.result); return; }
            if (state.status === 'cancelled') { activeJob = ''; setStatus('Search cancelled'); return; }
            if (state.status === 'error') { activeJob = ''; setStatus('Search error'); return; }
            pollTimer = windowObject.setTimeout(poll, 80);
          }).catch(function() { activeJob = ''; setStatus('Search error'); });
        }
        poll();
      }).catch(function(error) {
        setStatus(error.name === 'AbortError' ? 'Search cancelled' : (error.message === 'invalid_regular_expression' || error.message === 'unsafe_regular_expression' ? 'Invalid or unsafe regular expression' : 'Search error'));
      }).then(function() { aborter = null; });
    }
    function previewReplace() {
      if (controller.state.hasModifiedDocuments()) {
        setStatus('Save modified files before creating the preview.'); return;
      }
      var payload = searchPayload(); payload.replacement = replacementInput.value; previewToken = ''; applyButton.hidden = true;
      setStatus('Preparando vista previa…');
      jsonFetch(windowObject, '/api/navigation/replacements/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      }).then(function(preview) {
        clearResults(); previewToken = preview.token;
        preview.files.forEach(function(file) { button(file.path, file.matches + ' reemplazos', function() {}); });
        applyButton.hidden = false; setStatus(preview.total_matches + ' reemplazos en ' + preview.files.length + ' archivos · revisa y aprueba');
      }).catch(function(error) { setStatus(error.message === 'replacement_empty' ? 'There are no applicable replacements' : 'The preview could not be created'); });
    }
    function applyReplace() {
      if (!previewToken) { return; } applyButton.disabled = true; setStatus('Aplicando reemplazo aprobado…');
      jsonFetch(windowObject, '/api/navigation/replacements/apply', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: previewToken })
      }).then(function(payload) {
        previewToken = ''; applyButton.hidden = true; controller.reloadTree();
        return Promise.all(payload.applied.map(function(item) { return controller.api.read(item.path); })).then(function(documents) {
          controller.applyAresChanges(documents);
          setStatus('Reemplazo aplicado en ' + payload.applied.length + ' archivos.');
        });
      }).catch(function(error) { setStatus(error.message === 'version_conflict' ? 'Conflict: a file changed; the replacement was not applied.' : 'The replacement could not be applied.');
      }).then(function() { applyButton.disabled = false; });
    }
    function flattenNavigationTree(node, path, output) {
      if (!node) { return; }
      if (node.text && node.kind && node.kind !== 'module') {
        var span = node.spans && node.spans[0];
        output.push({ name: node.text, kind: node.kind, path: path, offset: span ? span.start : 0 });
      }
      (node.childItems || []).forEach(function(child) { flattenNavigationTree(child, path, output); });
    }
    function lineFromOffset(model, offset) {
      var position = model.getPositionAt ? model.getPositionAt(offset || 0) : { lineNumber: 1, column: 1 };
      return { line: position.lineNumber, column: position.column };
    }
    function workspaceSymbols() {
      var query = input.value, symbols = [], sequence = ++symbolSequence, phase = 'request';
      var python = windowObject.GeramPythonLsp && windowObject.GeramPythonLsp.workspaceSymbols ? windowObject.GeramPythonLsp.workspaceSymbols(query).catch(function() { return []; }) : Promise.resolve([]);
      var web = controller.editorReady.then(function(adapter) {
        var monaco = adapter.monaco;
        if (!monaco || !monaco.languages || !monaco.languages.typescript) { return []; }
        return jsonFetch(windowObject, '/api/navigation/files').then(function(payload) {
          var targets = (payload.files || []).filter(function(path) { return /\.(?:js|jsx|ts|tsx)$/i.test(path); }).slice(0, 200);
          return Promise.all(targets.map(function(path) {
            var existing = adapter.models.get(path);
            if (existing) { return [path, existing]; }
            return controller.api.read(path).then(function(file) {
              var uri = monaco.Uri.from({ scheme: 'geram-workspace', authority: 'local', path: '/' + path });
              var model = monaco.editor.getModel(uri) || monaco.editor.createModel(file.content, /\.tsx?$/i.test(path) ? 'typescript' : 'javascript', uri);
              return [path, { model: model }];
            }).catch(function() { return null; });
          }));
        }).then(function(entries) {
        var models = entries.filter(Boolean).filter(function(entry) { return /^(javascript|typescript)$/.test(entry[1].model.getLanguageId()); });
        var workers = models.map(function(entry) {
          var model = entry[1].model, path = entry[0];
          var factory = model.getLanguageId() === 'typescript' ? monaco.languages.typescript.getTypeScriptWorker : monaco.languages.typescript.getJavaScriptWorker;
          return factory().then(function(getWorker) { return getWorker(model.uri); }).then(function(worker) {
            return worker.getNavigationTree(model.uri.toString());
          }).then(function(tree) {
            var found = []; flattenNavigationTree(tree, path, found);
            return found.map(function(item) { var pos = lineFromOffset(model, item.offset); return Object.assign(item, pos); });
          }).catch(function() { return []; });
        });
        return Promise.all(workers).then(function(groups) { return groups.flat(); });
        });
      }).catch(function() { return []; });
      setStatus('Searching for symbols…');
      Promise.all([python, web]).then(function(groups) {
        if (sequence !== symbolSequence || mode !== 'symbols') { return; }
        phase = 'normalize-python';
        (groups[0] || []).forEach(function(item) {
          var path = item.location && item.location.uri ? item.location.uri.replace('file:///workspace/', '') : '';
          var start = item.location && item.location.range && item.location.range.start;
          if (path && start) { symbols.push({ name: item.name, kind: String(item.kind), path: path, line: start.line + 1, column: start.character + 1 }); }
        });
        phase = 'normalize-web';
        symbols = symbols.concat(groups[1] || []).filter(function(item) { return !query || item.name.toLowerCase().indexOf(query.toLowerCase()) >= 0; });
        phase = 'render';
        clearResults(); symbols.slice(0, 200).forEach(function(item) { button(item.name, item.kind + ' · ' + item.path, function() { openLocation(item); }); });
        setStatus(symbols.length ? symbols.length + ' symbols' : 'No symbols'); select(0);
      }).catch(function() { if (sequence === symbolSequence) { setStatus('Symbols could not be queried (' + phase + ').'); } });
    }
    function open(nextMode) {
      mode = nextMode; dialog.hidden = false; dialog.setAttribute('aria-hidden', 'false'); previewToken = ''; applyButton.hidden = true;
      searchOptions.hidden = mode === 'files' || mode === 'symbols'; replacementRow.hidden = mode !== 'search';
      searchOptions.style.display = searchOptions.hidden ? 'none' : ''; replacementRow.style.display = replacementRow.hidden ? 'none' : '';
      runButton.hidden = mode !== 'search';
      title.textContent = mode === 'files' ? 'QUICK OPEN' : (mode === 'symbols' ? 'WORKSPACE SYMBOLS' : 'GLOBAL SEARCH');
      input.value = ''; input.placeholder = mode === 'files' ? 'Search files…' : (mode === 'symbols' ? 'Search symbols…' : 'Search text…');
      clearResults(); setStatus(mode === 'files' ? 'Loading files…' : ''); input.focus();
      if (mode === 'files') { jsonFetch(windowObject, '/api/navigation/files').then(function(payload) { files = payload.files || []; renderFiles(); }).catch(function() { setStatus('Files could not be loaded.'); }); }
    }
    function cancelSearch() {
      if (aborter) { aborter.abort(); aborter = null; }
      if (pollTimer) { windowObject.clearTimeout(pollTimer); pollTimer = null; }
      if (activeJob) {
        windowObject.fetch('/api/navigation/search/jobs/' + encodeURIComponent(activeJob), { method: 'DELETE', credentials: 'same-origin' });
        activeJob = '';
      }
      setStatus('Search cancelled');
    }
    function close() { cancelSearch(); dialog.hidden = true; dialog.setAttribute('aria-hidden', 'true'); }

    input.addEventListener('input', function() {
      if (mode === 'files') { renderFiles(); }
      else if (mode === 'symbols') {
        if (symbolTimer) { windowObject.clearTimeout(symbolTimer); }
        symbolTimer = windowObject.setTimeout(function() { symbolTimer = null; workspaceSymbols(); }, 180);
      }
    });
    input.addEventListener('keydown', function(event) {
      if (event.key === 'ArrowDown') { event.preventDefault(); select(selected + 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); select(selected - 1); }
      else if (event.key === 'Enter') { event.preventDefault(); if (mode === 'search') { runSearch(); } else { var items = buttons(); if (items[selected]) { items[selected].click(); } } }
      else if (event.key === 'Escape') { close(); }
    });
    runButton.addEventListener('click', runSearch);
    documentObject.getElementById('workspaceReplacementPreview').addEventListener('click', previewReplace);
    applyButton.addEventListener('click', applyReplace);
    cancelButton.addEventListener('click', function() { if (aborter || activeJob) { cancelSearch(); } else { close(); } }); closeButton.addEventListener('click', close);
    documentObject.addEventListener('keydown', function(event) {
      var key = String(event.key).toLowerCase(), command = event.ctrlKey || event.metaKey;
      if (command && !event.shiftKey && key === 'p') { event.preventDefault(); open('files'); }
      else if (command && event.shiftKey && key === 'f') { event.preventDefault(); open('search'); }
      else if (command && !event.shiftKey && key === 't') { event.preventDefault(); open('symbols'); }
      else if (command && event.shiftKey && key === 'o') {
        event.preventDefault(); controller.editorReady.then(function(adapter) {
          var action = adapter.editor && adapter.editor.getAction('editor.action.quickOutline'); if (action) { action.run(); }
        });
      } else if (event.altKey && event.key === 'ArrowLeft') { event.preventDefault(); var back = history.back(); if (back) { openLocation(back, false); } }
      else if (event.altKey && event.key === 'ArrowRight') { event.preventDefault(); var forward = history.forward(); if (forward) { openLocation(forward, false); } }
    }, true);
    windowObject.addEventListener('geram:workspace-paths-changed', function(event) {
      var detail = event.detail || {}; files = []; symbolSequence += 1;
      (detail.mappings || []).forEach(function(mapping) {
        history.remap(mapping.oldPath, mapping.newPath, mapping.type);
        recent = recent.map(function(path) {
          if (path === mapping.oldPath) { return mapping.newPath; }
          return mapping.type === 'directory' && path.indexOf(mapping.oldPath + '/') === 0 ? mapping.newPath + path.slice(mapping.oldPath.length) : path;
        });
      });
      (detail.removed || []).forEach(function(item) {
        history.remove(item.path, item.type);
        recent = recent.filter(function(path) { return path !== item.path && !(item.type === 'directory' && path.indexOf(item.path + '/') === 0); });
      });
    });
    var navigation = { open: open, close: close, history: history, openLocation: openLocation };
    windowObject.GeramWorkspaceNavigation = navigation;
    return navigation;
  }

  return { initialize: initialize, fuzzyScore: fuzzyScore, NavigationHistory: NavigationHistory, filters: filters };
});
