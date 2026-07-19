(function(root, factory) {
  'use strict';
  var exported = factory();
  if (typeof module === 'object' && module.exports) { module.exports = exported; }
  if (root && root.document) { exported.initialize(root, root.document); }
})(typeof window !== 'undefined' ? window : null, function() {
  'use strict';

  function statusLabel(status) {
    return ({ queued: 'QUEUED', running: 'RUNNING', succeeded: 'PASSED', failed: 'FAILED', timed_out: 'TIMEOUT', cancelled: 'CANCELLED', unavailable: 'UNAVAILABLE', rejected: 'REJECTED', spawn_error: 'ERROR' })[status] || 'QUEUED';
  }
  function resultKey(item) { return [item.runner, item.path, item.selector || ''].join('|'); }
  function remapPath(path, mappings) {
    var current = path;
    (mappings || []).forEach(function(mapping) {
      if (current === mapping.oldPath) { current = mapping.newPath; }
      else if (mapping.type === 'directory' && current.indexOf(mapping.oldPath + '/') === 0) { current = mapping.newPath + current.slice(mapping.oldPath.length); }
    });
    return current;
  }
  function isRemovedPath(path, removed) {
    return (removed || []).some(function(item) {
      return path === item.path || (item.type === 'directory' && path.indexOf(item.path + '/') === 0);
    });
  }
  function failureLocation(stderr, fallbackPath) {
    var expression = /File "(?:\/workspace\/)?([^"\n]+)", line (\d+)/g, match, last = null;
    while ((match = expression.exec(String(stderr || '')))) {
      if (match[1].indexOf('/') === 0 || match[1].indexOf('..') >= 0) { continue; }
      last = { path: match[1] || fallbackPath, line: Number(match[2]), column: 1 };
    }
    return last || (fallbackPath ? { path: fallbackPath, line: 1, column: 1 } : null);
  }

  function initialize(windowObject, documentObject) {
    var controller = windowObject.GeramWorkspaceController;
    if (!controller || documentObject.getElementById('testingPanel')) { return null; }
    var discovery = { files: [], total: 0 }, scripts = [], results = new Map(), lastRequest = null;
    var currentRunId = '', currentRequest = null, queue = [], pollTimer = null, generation = 0;

    function node(tag, className, text) {
      var item = documentObject.createElement(tag); if (className) { item.className = className; }
      if (text !== undefined) { item.textContent = text; } return item;
    }
    function request(path, options) {
      return windowObject.fetch(path, Object.assign({ credentials: 'same-origin', cache: 'no-store' }, options || {})).then(function(response) {
        if (response.ok) { return response.json(); }
        return response.json().then(function(payload) { var error = new Error(payload && payload.detail && payload.detail.code || 'testing_failed'); error.code = error.message; throw error; });
      });
    }
    function post(path, payload) { return request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); }
    function openLocation(path, line, column) {
      if (controller.state.has(path)) { return controller.navigate(path, line || 1, column || 1); }
      return controller.api.read(path).then(function(file) {
        controller.state.load(file); return controller.navigate(path, line || 1, column || 1);
      }).catch(function() { status.textContent = 'Could not open the related location.'; return false; });
    }

    var panel = node('section', 'testing-panel'); panel.id = 'testingPanel'; panel.hidden = true; panel.setAttribute('aria-hidden', 'true'); panel.setAttribute('aria-label', 'Safe testing');
    var header = node('div', 'testing-head'); var title = node('h3', '', 'TESTING · BUBBLEWRAP');
    var counter = node('span', 'testing-counter', '0/0'); var refresh = node('button', '', '↻'); refresh.type = 'button'; refresh.title = 'Rediscover tests';
    var close = node('button', '', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Close Testing');
    header.appendChild(title); header.appendChild(counter); header.appendChild(refresh); header.appendChild(close);
    var notice = node('p', 'testing-notice', 'TestRunSpec → Sandbox Guard → Bubblewrap → Terminal Watcher. No shell, network, or fallback.');
    var status = node('p', 'testing-status', 'Discovery pending.'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    var actions = node('div', 'testing-actions');
    function action(label, handler) { var button = node('button', '', label); button.type = 'button'; button.addEventListener('click', handler); actions.appendChild(button); return button; }
    var runActiveButton = action('Run file', runActiveFile);
    var runAllButton = action('Run all', runAll);
    var cancelButton = action('Cancel', cancel); cancelButton.hidden = true;
    var repeatButton = action('Repeat last', repeatLast); repeatButton.disabled = true;
    var clearButton = action('Clear results', clearResults);
    var list = node('ul', 'testing-list'); list.setAttribute('aria-label', 'Detected tests and scripts');
    var detail = node('section', 'testing-detail'); detail.hidden = true;
    var detailHead = node('div', 'testing-detail-head'); var detailTitle = node('strong', '', 'RESULT');
    var navigate = node('button', '', 'Open location'); navigate.type = 'button'; navigate.hidden = true;
    var detailClose = node('button', '', '×'); detailClose.type = 'button'; detailClose.setAttribute('aria-label', 'Close result');
    detailHead.appendChild(detailTitle); detailHead.appendChild(navigate); detailHead.appendChild(detailClose);
    var meta = node('p', 'testing-meta'); var stdoutLabel = node('strong', '', 'stdout'); var stdout = node('pre', 'testing-output');
    var stderrLabel = node('strong', '', 'stderr'); var stderr = node('pre', 'testing-output error');
    [detailHead, meta, stdoutLabel, stdout, stderrLabel, stderr].forEach(function(item) { detail.appendChild(item); });
    [header, notice, status, actions, list, detail].forEach(function(item) { panel.appendChild(item); }); documentObject.body.appendChild(panel);

    function allDescriptors() {
      var items = [];
      discovery.files.forEach(function(file) {
        items.push({ runner: 'python_unittest', path: file.path, selector: '', label: file.path, line: 1, kind: 'file-tests' });
        file.classes.forEach(function(testClass) {
          items.push({ runner: 'python_unittest', path: file.path, selector: testClass.selector, label: testClass.name, line: testClass.line, kind: 'class' });
          testClass.methods.forEach(function(method) { items.push({ runner: 'python_unittest', path: file.path, selector: method.selector, label: method.name, line: method.line, kind: 'method' }); });
        });
      });
      scripts.forEach(function(path) { items.push({ runner: 'node_script', path: path, selector: '', label: path, line: 1, kind: 'script' }); });
      return items;
    }
    function updateCounter() {
      var completed = Array.from(results.values()).filter(function(result) { return !['queued', 'running'].includes(result.status); });
      var passed = completed.filter(function(result) { return result.status === 'succeeded'; }).length;
      counter.textContent = passed + '/' + completed.length + ' passed · ' + discovery.total + ' tests';
    }
    function render() {
      while (list.firstChild) { list.removeChild(list.firstChild); }
      allDescriptors().forEach(function(item) {
        var row = node('li', 'testing-item testing-' + item.kind); row.tabIndex = 0;
        var state = results.get(resultKey(item)); var icon = node('span', 'testing-state ' + (state ? state.status : 'idle'), state ? statusLabel(state.status) : 'PENDING');
        var name = node('button', 'testing-name', item.label); name.type = 'button'; name.title = item.path + ':' + item.line;
        name.addEventListener('click', function() { openLocation(item.path, item.line || 1, 1); });
        var run = node('button', 'testing-run', '▷'); run.type = 'button'; run.title = 'Run ' + item.label; run.disabled = Boolean(currentRunId); run.addEventListener('click', function() { enqueue([item]); });
        var duration = node('span', 'testing-duration', state && typeof state.duration_seconds === 'number' ? state.duration_seconds.toFixed(2) + ' s' : '—');
        row.appendChild(icon); row.appendChild(name); row.appendChild(duration); row.appendChild(run);
        if (state) { row.addEventListener('dblclick', function() { showResult(item, state); }); }
        list.appendChild(row);
      });
      updateCounter(); runAllButton.disabled = Boolean(currentRunId) || discovery.files.length === 0; runActiveButton.disabled = Boolean(currentRunId) || !/\.(?:py|js)$/i.test(controller.activePath() || '');
    }
    function discover() {
      var selectedGeneration = ++generation; status.textContent = 'Analyzing AST without importing modules…';
      return Promise.all([request('/api/testing/discovery'), controller.api.tree()]).then(function(values) {
        if (selectedGeneration !== generation) { return; }
        discovery = values[0]; scripts = (values[1].entries || []).filter(function(entry) { return entry.type === 'file' && entry.editable !== false && /\.js$/i.test(entry.path); }).map(function(entry) { return entry.path; });
        status.textContent = discovery.total + ' unittest test(s) and ' + scripts.length + ' JavaScript script(s) detected.'; render(); registerCodeLens();
      }).catch(function() { status.textContent = 'Safe discovery could not be completed.'; status.classList.add('error'); });
    }
    function ensureSaved(path) {
      var info = controller.documentInfo(path); if (!info || !info.modified) { return Promise.resolve(true); }
      if (!windowObject.confirm('There are unsaved changes in ' + path + '. Save them before running?')) { return Promise.resolve(false); }
      var original = controller.activePath();
      return controller.navigate(path, 1, 1).then(function() { return controller.save(); }).then(function(result) {
        if (!result || !result.ok || (controller.documentInfo(path) && controller.documentInfo(path).modified)) { return false; }
        if (original && original !== path && controller.state.has(original)) { return controller.navigate(original, 1, 1).then(function() { return true; }); }
        return true;
      });
    }
    function enqueue(items) {
      if (currentRunId || !items.length) { return; }
      queue = items.slice(); runNext();
    }
    function runNext() {
      if (!queue.length) { currentRequest = null; cancelButton.hidden = true; render(); return; }
      var item = queue.shift(); currentRequest = item; lastRequest = Object.assign({}, item); repeatButton.disabled = false;
      ensureSaved(item.path).then(function(saved) {
        if (!saved) { status.textContent = 'Run cancelled: the current version was not saved.'; queue = []; currentRequest = null; render(); return null; }
        results.set(resultKey(item), { status: 'queued', duration_seconds: null }); render(); status.textContent = 'Pendiente: ' + item.label;
        return post('/api/testing/runs', { runner: item.runner, target: item.path, selector: item.selector || '', timeout_seconds: 30 });
      }).then(function(result) {
        if (!result) { return; }
        if (!result.run_id || !['queued', 'running'].includes(result.status)) {
          results.set(resultKey(item), result); status.textContent = result.error === 'sandbox_unavailable' ? 'Bubblewrap is unavailable; the run was rejected.' : (result.error === 'node_unavailable' ? 'A trusted Node runtime is unavailable.' : 'The secure runner rejected the run.');
          queue = []; currentRequest = null; render(); return;
        }
        currentRunId = result.run_id; cancelButton.hidden = false; poll();
      }).catch(function() { status.textContent = 'The secure runner could not be started.'; queue = []; currentRequest = null; render(); });
    }
    function poll() {
      if (!currentRunId || !currentRequest) { return; }
      var requestedRunId = currentRunId, requestedItem = currentRequest;
      request('/api/terminal-watcher/runs/' + encodeURIComponent(requestedRunId)).then(function(result) {
        if (currentRunId !== requestedRunId || !currentRequest) { return; }
        results.set(resultKey(requestedItem), result); status.textContent = statusLabel(result.status) + ': ' + requestedItem.label; render();
        if (['queued', 'running'].includes(result.status) || result.cleanup_status === 'pending') {
          pollTimer = windowObject.setTimeout(poll, 250); return;
        }
        currentRunId = ''; cancelButton.hidden = true; showResult(requestedItem, result); runNext();
      }).catch(function() {
        if (currentRunId !== requestedRunId) { return; }
        status.textContent = 'Terminal Watcher could not be queried.'; currentRunId = ''; queue = []; render();
      });
    }
    function showResult(item, result) {
      detail.hidden = false; detailTitle.textContent = statusLabel(result.status) + ' · ' + item.label;
      var exitCode = result.returncode === undefined ? result.exit_code : result.returncode;
      meta.textContent = 'runner: ' + (result.purpose || item.runner) + ' · exit code: ' + (exitCode === null || exitCode === undefined ? '—' : exitCode) + ' · duration: ' + (typeof result.duration_seconds === 'number' ? result.duration_seconds.toFixed(2) + ' s' : '—') + ' · sandbox_backend: ' + (result.sandbox_backend || '—') + ' · cleanup_status: ' + (result.cleanup_status || '—') + (result.termination_reason ? ' · ' + result.termination_reason : '');
      stdout.textContent = result.stdout || ''; stderr.textContent = result.stderr || result.error || '';
      var location = failureLocation(result.stderr, item.path); navigate.hidden = !location; navigate.onclick = function() { if (location) { openLocation(location.path, location.line, location.column); } };
    }
    function cancel() {
      queue = [];
      if (!currentRunId) { return; }
      post('/api/terminal-watcher/runs/' + encodeURIComponent(currentRunId) + '/cancel', {}).then(function() { if (pollTimer) { windowObject.clearTimeout(pollTimer); } poll(); }).catch(function() { status.textContent = 'The run could not be cancelled.'; });
    }
    function runAll() {
      enqueue(discovery.files.map(function(file) { return { runner: 'python_unittest', path: file.path, selector: '', label: file.path, line: 1, kind: 'file-tests' }; }));
    }
    function runActiveFile() {
      var path = controller.activePath(); if (!/\.(?:py|js)$/i.test(path || '')) { return; }
      enqueue([{ runner: /\.js$/i.test(path) ? 'node_script' : 'python_file', path: path, selector: '', label: path, line: 1, kind: /\.js$/i.test(path) ? 'script' : 'python-file' }]);
    }
    function repeatLast() { if (lastRequest) { enqueue([Object.assign({}, lastRequest)]); } }
    function clearResults() { results.clear(); detail.hidden = true; render(); status.textContent = 'Session results cleared.'; }

    var codeLensRegistered = false;
    function registerCodeLens() {
      if (codeLensRegistered) { return; }
      controller.editorReady.then(function(adapter) {
        var monaco = adapter.monaco; if (!monaco || !monaco.languages || typeof monaco.languages.registerCodeLensProvider !== 'function') { return; }
        codeLensRegistered = true;
        if (monaco.editor && typeof monaco.editor.registerCommand === 'function') {
          monaco.editor.registerCommand('geram.testing.run', function(_accessor, item) { enqueue([item]); });
        }
        monaco.languages.registerCodeLensProvider('python', { provideCodeLenses: function(model) {
          var path = windowObject.GeramMonacoEditor.pathFromWorkspaceUri(model.uri); var lenses = [];
          allDescriptors().filter(function(item) { return item.path === path && ['class', 'method'].includes(item.kind); }).forEach(function(item) {
            lenses.push({ range: { startLineNumber: item.line, startColumn: 1, endLineNumber: item.line, endColumn: 1 }, command: { id: 'geram.testing.run', title: '▷ Run ' + item.label, arguments: [item] } });
          }); return { lenses: lenses, dispose: function() {} };
        }, resolveCodeLens: function(_model, lens) { return lens; } });
      });
    }
    function handlePaths(event) {
      var detailValue = event.detail || {}, next = new Map();
      results.forEach(function(value, key) {
        var parts = key.split('|'), path = remapPath(parts[1], detailValue.mappings || []);
        var removed = isRemovedPath(path, detailValue.removed);
        if (!removed) { next.set([parts[0], path, parts[2]].join('|'), value); }
      });
      results.clear(); next.forEach(function(value, key) { results.set(key, value); }); discover();
    }

    function setPanelOpen(open) {
      panel.hidden = !open;
      panel.setAttribute('aria-hidden', open ? 'false' : 'true');
      var activity = documentObject.querySelector('[data-act="testing"]');
      if (activity) {
        activity.classList.toggle('activo', open);
        activity.setAttribute('aria-expanded', open ? 'true' : 'false');
      }
      if (open) { discover(); }
    }

    close.addEventListener('click', function() { setPanelOpen(false); });
    refresh.addEventListener('click', discover); detailClose.addEventListener('click', function() { detail.hidden = true; });
    windowObject.addEventListener('geram:workspace-paths-changed', handlePaths);
    documentObject.addEventListener('keydown', function(event) { if ((event.ctrlKey || event.metaKey) && event.shiftKey && String(event.key).toLowerCase() === 't') { event.preventDefault(); setPanelOpen(true); } }, true);
    Array.from(documentObject.querySelectorAll('[data-act="testing"]')).forEach(function(activity) {
      activity.addEventListener('click', function(event) { event.preventDefault(); event.stopImmediatePropagation(); setPanelOpen(true); }, true);
    });
    discover(); render();
    var publicApi = { discover: discover, open: function() { setPanelOpen(true); }, close: function() { setPanelOpen(false); }, run: function(item) { enqueue([item]); }, cancel: cancel, results: results };
    windowObject.GeramTesting = publicApi; return publicApi;
  }

  return { initialize: initialize, statusLabel: statusLabel, resultKey: resultKey, remapPath: remapPath, isRemovedPath: isRemovedPath, failureLocation: failureLocation };
});
