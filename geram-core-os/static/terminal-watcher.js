(function (windowObject, documentObject) {
  'use strict';
  var panel = documentObject.getElementById('terminalWatcherPanel');
  var toggle = documentObject.getElementById('toggleTerminalWatcher');
  var list = documentObject.getElementById('terminalWatcherRuns');
  if (!panel || !toggle || !list) return;
  var timer = null;
  function setOpen(open) {
    panel.hidden = !open;
    toggle.classList.toggle('activo', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function render(runs) {
    while (list.firstChild) list.removeChild(list.firstChild);
    runs.forEach(function (run) {
      var item = documentObject.createElement('article');
      var title = documentObject.createElement('h3'); title.textContent = run.purpose + ' · ' + run.status;
      var meta = documentObject.createElement('p'); meta.textContent = 'cwd: ' + run.cwd + ' · duration: ' + (run.duration_seconds || 0).toFixed(2) + ' s';
      var out = documentObject.createElement('pre'); out.textContent = run.stdout || '';
      var err = documentObject.createElement('pre'); err.textContent = run.stderr || ''; err.className = 'terminal-watcher-stderr';
      item.appendChild(title); item.appendChild(meta); item.appendChild(out); item.appendChild(err);
      if (run.status === 'running' || run.status === 'queued') {
        var button = documentObject.createElement('button'); button.type = 'button'; button.textContent = (root.GeramI18n ? root.GeramI18n.t('common.cancel') : 'Cancel');
        button.addEventListener('click', function () { fetch('/api/terminal-watcher/runs/' + encodeURIComponent(run.run_id) + '/cancel', { method: 'POST' }).then(poll); }); item.appendChild(button);
      }
      list.appendChild(item);
    });
  }
  function poll() { return fetch('/api/terminal-watcher/runs', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) { render(d.runs || []); if ((d.runs || []).some(function (r) { return r.status === 'running' || r.status === 'queued'; })) timer = windowObject.setTimeout(poll, 500); }); }
  toggle.addEventListener('click', function () {
    setOpen(panel.hidden);
    if (!panel.hidden) { poll(); }
    else if (timer) { windowObject.clearTimeout(timer); timer = null; }
  });
  documentObject.addEventListener('keydown', function(event) {
    if (event.key === 'Escape' && !panel.hidden) {
      setOpen(false);
      if (timer) { windowObject.clearTimeout(timer); timer = null; }
      toggle.focus();
    }
  });
}(window, document));
