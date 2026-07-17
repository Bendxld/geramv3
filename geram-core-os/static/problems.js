(function(root, factory) {
  'use strict';
  var exported = factory();
  if (typeof module === 'object' && module.exports) { module.exports = exported; }
  if (root && root.document) { exported.initialize(root, root.document); }
})(typeof window !== 'undefined' ? window : null, function() {
  'use strict';

  function normalizeProblems(payload) {
    var source = payload && Array.isArray(payload.problems) ? payload.problems : [];
    return source.filter(function(item) {
      return item && typeof item.path === 'string' && typeof item.message === 'string' &&
        (item.severity === 8 || item.severity === 4);
    }).map(function(item) {
      return {
        path: item.path,
        message: item.message,
        source: typeof item.source === 'string' ? item.source : '',
        severity: item.severity,
        line: Math.max(1, Number(item.line) || 1),
        column: Math.max(1, Number(item.column) || 1)
      };
    });
  }

  function initialize(root, documentObject) {
    var panel = documentObject.getElementById('workspaceProblems');
    var toggle = documentObject.getElementById('workspaceProblemsToggle');
    var close = documentObject.getElementById('workspaceProblemsClose');
    var count = documentObject.getElementById('workspaceProblemsCount');
    var summary = documentObject.getElementById('workspaceProblemsSummary');
    var list = documentObject.getElementById('workspaceProblemsList');
    if (!panel || !toggle || !close || !count || !summary || !list) { return null; }
    var sources = { monaco: [], python: [] };
    var problems = [];

    function setOpen(open) {
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function render() {
      while (list.firstChild) { list.removeChild(list.firstChild); }
      var errors = problems.filter(function(item) { return item.severity === 8; }).length;
      var warnings = problems.length - errors;
      count.textContent = String(problems.length);
      summary.textContent = problems.length ? errors + ' errors · ' + warnings + ' warnings' : 'No problems';
      toggle.classList.toggle('has-errors', errors > 0);
      toggle.classList.toggle('has-warnings', warnings > 0);
      problems.forEach(function(problem) {
        var item = documentObject.createElement('li');
        var button = documentObject.createElement('button');
        button.type = 'button';
        button.className = 'workspace-problem ' + (problem.severity === 8 ? 'error' : 'warning');
        var message = documentObject.createElement('span');
        message.textContent = problem.message;
        var location = documentObject.createElement('span');
        location.className = 'workspace-problem-location';
        location.textContent = problem.path + ':' + problem.line + ':' + problem.column;
        button.appendChild(message);
        button.appendChild(location);
        button.addEventListener('click', function() {
          var controller = root.GeramWorkspaceController;
          if (controller && typeof controller.navigate === 'function') {
            controller.navigate(problem.path, problem.line, problem.column);
          }
        });
        item.appendChild(button);
        list.appendChild(item);
      });
    }

    function updateSource(name, event) {
      sources[name] = normalizeProblems(event && event.detail);
      problems = sources.monaco.concat(sources.python);
      render();
    }
    root.addEventListener('geram:problems', function(event) { updateSource('monaco', event); });
    root.addEventListener('geram:python-problems', function(event) { updateSource('python', event); });
    root.addEventListener('geram:toggle-problems', function() { setOpen(panel.hidden); });
    toggle.addEventListener('click', function() { setOpen(panel.hidden); });
    close.addEventListener('click', function() { setOpen(false); });
    documentObject.addEventListener('keydown', function(event) {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && String(event.key).toLowerCase() === 'm') {
        event.preventDefault();
        setOpen(panel.hidden);
      }
    }, true);
    render();
    return { render: render, setOpen: setOpen };
  }

  return { initialize: initialize, normalizeProblems: normalizeProblems };
});
