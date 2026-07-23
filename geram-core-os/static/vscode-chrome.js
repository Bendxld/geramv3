// ============================================================
// GERAM CORE OS · vscode-chrome.js (v3, Paso 3)
// Cromática estilo VS Code en el renderer: menú superior (File/Edit/…),
// activity bar izquierda con badges neón, colapso del explorador, badge
// numérico de Source Control (git) y sign-in con GitHub (token local).
// Nada usa innerHTML; los dropdowns se construyen con createElement.
// ============================================================
(function (root) {
  'use strict';
  if (!root || !root.document) { return; }
  var documentObject = root.document;
  var $ = function (id) { return documentObject.getElementById(id); };

  // ---- Acceso al editor Monaco (para acciones del menú) ----
  var editorAdapter = null;
  (function () {
    var controller = root.GeramWorkspaceController;
    if (controller && controller.editorReady && controller.editorReady.then) {
      controller.editorReady.then(function (adapter) { editorAdapter = adapter; }).catch(function () {});
    }
  })();
  function runEditorAction(actionId) {
    if (editorAdapter && editorAdapter.editor && typeof editorAdapter.editor.getAction === 'function') {
      var action = editorAdapter.editor.getAction(actionId);
      if (action) { editorAdapter.editor.focus(); action.run(); return true; }
    }
    return false;
  }
  function triggerEditor(command) {
    if (editorAdapter && editorAdapter.editor && typeof editorAdapter.editor.trigger === 'function') {
      editorAdapter.editor.focus();
      editorAdapter.editor.trigger('menu', command, null);
    }
  }

  // ---- Toast ligero para acciones informativas ----
  var toastTimer = null;
  function t(key) {
    var i18n = root.GeramI18n;
    return (i18n && i18n.t) ? i18n.t(key) : key;
  }
  function toast(message) {
    var el = $('vscodeToast');
    if (!el) {
      el = documentObject.createElement('div');
      el.id = 'vscodeToast';
      el.className = 'vscode-toast';
      documentObject.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add('visible');
    if (toastTimer) { root.clearTimeout(toastTimer); }
    toastTimer = root.setTimeout(function () { el.classList.remove('visible'); }, 2600);
  }

  function clickIf(id) { var el = $(id); if (el) { el.click(); } }
  function focusAiBar(prefill) {
    var input = $('inlineAiInput');
    if (input) { if (prefill) { input.value = prefill; } input.focus(); }
  }
  // El modal de nuevo proyecto y el refresco del explorador los expone inline-ai.js.
  function newProject() { if (typeof root.GeramNewProject === 'function') { root.GeramNewProject(); } else { focusAiBar('create a project '); } }
  function refreshExplorer() { if (typeof root.GeramRefreshExplorer === 'function') { root.GeramRefreshExplorer(); } }
  function toggleExplorer() {
    var collapsed = documentObject.body.classList.toggle('explorer-collapsed');
    setActive('explorer', !collapsed);
    if (editorAdapter && editorAdapter.layout) { root.setTimeout(function () { editorAdapter.layout(); }, 60); }
  }
  function toggleMinimap() {
    if (editorAdapter && editorAdapter.editor && editorAdapter.editor.getOption && editorAdapter.editor.updateOptions) {
      // 57 ~ EditorOption.minimap; usamos getOption con fallback a un flag local.
      minimapOn = !minimapOn;
      editorAdapter.editor.updateOptions({ minimap: { enabled: minimapOn } });
      toast(t('toast.minimap') + (minimapOn ? 'ON' : 'OFF'));
    }
  }
  var minimapOn = true;

  function runTestsActive() {
    var controller = root.GeramWorkspaceController;
    var path = controller && controller.activePath && controller.activePath();
    if (!path) { toast(t('toast.openfiletests')); return; }
    toast(t('toast.runningtests'));
    root.fetch('/api/ares/tests', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: 'local', runner: 'python_unittest', target: path, timeout_seconds: 30 })
    }).then(function (r) { return r.json(); })
      .then(function (d) { toast('Test Runner: ' + (d && d.status ? d.status : t('toast.unknown'))); })
      .catch(function () { toast(t('toast.testsfail')); });
  }

  function runActiveFile() {
    var controller = root.GeramWorkspaceController;
    var path = controller && controller.activePath && controller.activePath();
    if (!path) { toast(t('toast.openpyjs')); return; }
    var button = $('inlineAiRunFile');
    if (!button || button.hidden) {
      toast(t('toast.saferun'));
      return;
    }
    button.click();
  }

  function openGlobalSearch() {
    var navigation = root.GeramWorkspaceNavigation;
    if (navigation && typeof navigation.open === 'function') {
      navigation.open('search');
      return;
    }
    toast(t('toast.searchnotready'));
  }

  // ---- Definición de menús (label, atajo visible, acción) ----
  var MENUS = {
    file: [
      { label: 'menui.newproject', key: 'Ctrl+Shift+N', run: function () { newProject(); } },
      { label: 'menui.openfolder', key: 'Ctrl+K Ctrl+O', run: function () {
        if (root.GeramOpenFolder) { root.GeramOpenFolder.open(); return; }
        toast(t('toast.nofolderpicker'));
      } },
      { label: 'menui.toggleexplorer', key: 'Ctrl+Shift+E', run: toggleExplorer },
      { sep: true },
      { label: 'menui.uploadfiles', run: function () {
        if (root.GeramWorkspaceUpload) { root.GeramWorkspaceUpload.files(); return; }
        toast(t('toast.noupload'));
      } },
      { label: 'menui.uploadfolder', run: function () {
        if (root.GeramWorkspaceUpload) { root.GeramWorkspaceUpload.folder(); return; }
        toast(t('toast.noupload'));
      } },
      { sep: true },
      { label: 'menui.save', key: 'Ctrl+S', run: function () { clickIf('workspaceGuardar'); } },
      { label: 'menui.github', run: openGithub }
    ],
    edit: [
      { label: 'menui.undo', key: 'Ctrl+Z', run: function () { triggerEditor('undo'); } },
      { label: 'menui.redo', key: 'Ctrl+Y', run: function () { triggerEditor('redo'); } },
      { sep: true },
      { label: 'menui.cut', key: 'Ctrl+X', run: function () { runEditorAction('editor.action.clipboardCutAction'); } },
      { label: 'menui.copy', key: 'Ctrl+C', run: function () { runEditorAction('editor.action.clipboardCopyAction'); } },
      { label: 'menui.paste', key: 'Ctrl+V', run: function () { runEditorAction('editor.action.clipboardPasteAction'); } },
      { sep: true },
      { label: 'menui.find', key: 'Ctrl+F', run: function () { runEditorAction('actions.find'); } },
      { label: 'menui.replace', key: 'Ctrl+H', run: function () { runEditorAction('editor.action.startFindReplaceAction'); } }
    ],
    selection: [
      { label: 'menui.selectall', key: 'Ctrl+A', run: function () { runEditorAction('editor.action.selectAll'); } },
      { label: 'menui.copylinedown', key: 'Shift+Alt+Down', run: function () { runEditorAction('editor.action.copyLinesDownAction'); } },
      { label: 'menui.addcursor', key: 'Ctrl+Alt+Down', run: function () { runEditorAction('editor.action.insertCursorBelow'); } }
    ],
    view: [
      { label: 'menui.toggleexplorer', key: 'Ctrl+Shift+E', run: toggleExplorer },
      { label: 'menui.refreshexplorer', run: refreshExplorer },
      { label: 'menui.toggleterminal', key: 'Ctrl+`', run: function () { clickIf('toggleTerminalWatcher'); } },
      { label: 'menui.toggleminimap', run: toggleMinimap },
      { label: 'menui.palette', key: 'Ctrl+Shift+P', run: function () { runEditorAction('editor.action.quickCommand'); } }
    ],
    go: [
      { label: 'menui.gotoline', key: 'Ctrl+G', run: function () { runEditorAction('editor.action.gotoLine'); } },
      { label: 'menui.gotosymbol', key: 'Ctrl+Shift+O', run: function () { runEditorAction('editor.action.quickOutline'); } }
    ],
    run: [
      { label: 'menui.runfile', key: 'Ctrl+F5', run: runActiveFile },
      { label: 'menui.runtests', key: 'Ctrl+Shift+T', run: runTestsActive },
      { label: 'menui.askares', key: 'Ctrl+I', run: function () { focusAiBar(''); } }
    ],
    terminal: [
      { label: 'menui.toggleterminal', key: 'Ctrl+`', run: function () { clickIf('toggleTerminalWatcher'); } }
    ],
    help: [
      { label: 'menui.irismanual', key: 'F1', run: function () {
        if (root.GeramManual && typeof root.GeramManual.open === 'function') {
          root.GeramManual.open('iris');
        }
      } },
      { label: 'menui.aresmanual', run: function () {
        if (root.GeramManual && typeof root.GeramManual.open === 'function') {
          root.GeramManual.open('ares');
        }
      } },
      { sep: true },
      { label: 'menui.about', run: function () { toast('GERAM CORE OS · v3 · editor local-first con A.R.E.S.'); } }
    ]
  };

  var openMenu = null;
  function cerrarMenu() {
    if (openMenu) { openMenu.classList.remove('abierto'); openMenu = null; }
    var dd = $('vscodeDropdown');
    if (dd) { dd.remove(); }
  }
  function abrirMenu(button) {
    cerrarMenu();
    var name = button.getAttribute('data-menu');
    var items = MENUS[name] || [];
    var dd = documentObject.createElement('div');
    dd.id = 'vscodeDropdown';
    dd.className = 'vscode-dropdown';
    var rect = button.getBoundingClientRect();
    dd.style.left = rect.left + 'px';
    dd.style.top = rect.bottom + 'px';
    items.forEach(function (item) {
      if (item.sep) {
        var hr = documentObject.createElement('div');
        hr.className = 'vscode-dropdown-sep';
        dd.appendChild(hr);
        return;
      }
      var row = documentObject.createElement('button');
      row.type = 'button';
      row.className = 'vscode-dropdown-item';
      var label = documentObject.createElement('span');
      label.textContent = t(item.label);
      row.appendChild(label);
      if (item.key) {
        var key = documentObject.createElement('span');
        key.className = 'vscode-dropdown-key';
        key.textContent = item.key;
        row.appendChild(key);
      }
      row.addEventListener('click', function () { cerrarMenu(); try { item.run(); } catch (e) { /* noop */ } });
      dd.appendChild(row);
    });
    documentObject.body.appendChild(dd);
    button.classList.add('abierto');
    openMenu = button;
  }

  function wireMenubar() {
    var buttons = documentObject.querySelectorAll('.vscode-menu');
    buttons.forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        if (openMenu === button) { cerrarMenu(); } else { abrirMenu(button); }
      });
      button.addEventListener('mouseenter', function () { if (openMenu && openMenu !== button) { abrirMenu(button); } });
    });
    documentObject.addEventListener('click', cerrarMenu);
  }

  // ---- Activity Bar ----
  function setActive(act, isActive) {
    var btn = documentObject.querySelector('.act-btn[data-act="' + act + '"]');
    if (btn) { btn.classList.toggle('activo', isActive !== false); }
  }
  var ACT_HANDLERS = {
    explorer: toggleExplorer,
    search: openGlobalSearch,
    // Source Control and Testing own their real panels and capture the click.
    scm: function () {},
    run: runActiveFile,
    // extensions-panel.js conecta y refleja el estado del gestor real.
    extensions: function () {},
    testing: function () {},
    terminal: function () {}
  };
  function wireActivityBar() {
    documentObject.querySelectorAll('.act-btn[data-act]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var act = btn.getAttribute('data-act');
        // marca activo (uno a la vez, salvo el explorador que es toggle real)
        if (act !== 'explorer' && act !== 'extensions' && act !== 'terminal') {
          documentObject.querySelectorAll('.act-btn[data-act]').forEach(function (b) { b.classList.remove('activo'); });
          btn.classList.add('activo');
        }
        var handler = ACT_HANDLERS[act];
        if (handler) { handler(); }
      });
    });
    var gh = $('actGithub');
    if (gh) { gh.addEventListener('click', openGithub); }
  }

  // ---- Badge de Source Control (git) + estado ----
  var lastChanges = 0, lastBranch = null;
  function cargarBadges() {
    root.fetch('/api/workspace/status', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (status) {
        if (!status) { return; }
        lastChanges = status.changes || 0;
        lastBranch = status.branch || null;
        var badge = $('actBadgeScm');
        if (badge) {
          if (lastChanges > 0) { badge.textContent = String(lastChanges); badge.hidden = false; }
          else { badge.hidden = true; }
        }
      }).catch(function () {});
  }

  // ---- Sign in with GitHub ----
  function openGithub() { var m = $('githubModal'); if (m) { m.classList.add('activo'); m.setAttribute('aria-hidden', 'false'); refreshGithub(); var i = $('githubTokenInput'); if (i) { i.focus(); } } }
  function closeGithub() { var m = $('githubModal'); if (m) { m.classList.remove('activo'); m.setAttribute('aria-hidden', 'true'); } }
  function pintarGithub(status) {
    var estado = $('githubModalEstado');
    var dot = $('actGithubDot');
    var connected = Boolean(status && status.connected);
    if (estado) { estado.textContent = connected ? (status.login ? t('gh.connectedas').replace('{login}', status.login) : t('gh.connected')) : t('gh.notconnected'); }
    if (dot) { dot.hidden = !connected; }
    var gh = $('actGithub');
    if (gh) { gh.classList.toggle('conectado', connected); gh.title = connected ? ('GitHub: @' + (status.login || 'conectado')) : 'Sign in with GitHub'; }
  }
  function refreshGithub() {
    root.fetch('/api/github/status', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) { pintarGithub(s); } }).catch(function () {});
  }
  function guardarGithub() {
    var input = $('githubTokenInput');
    var token = input ? input.value.trim() : '';
    if (!token) { var e = $('githubModalEstado'); if (e) { e.textContent = t('gh.pastetoken'); } return; }
    root.fetch('/api/github/token', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: token }) })
      .then(function (r) { return r.json(); })
      .then(function (s) { if (input) { input.value = ''; } pintarGithub(s); toast(t('gh.connectedtoast')); })
      .catch(function () { var e = $('githubModalEstado'); if (e) { e.textContent = t('gh.connectfail'); } });
  }
  function salirGithub() {
    root.fetch('/api/github/token', { method: 'DELETE' })
      .then(function (r) { return r.json(); })
      .then(function (s) { pintarGithub(s); toast(t('gh.signedout')); })
      .catch(function () {});
  }
  function wireGithub() {
    var g = $('githubGuardar'); if (g) { g.addEventListener('click', guardarGithub); }
    var s = $('githubSalir'); if (s) { s.addEventListener('click', salirGithub); }
    var c = $('githubModalCerrar'); if (c) { c.addEventListener('click', closeGithub); }
    var f = $('githubModalFondo'); if (f) { f.addEventListener('click', closeGithub); }
    var input = $('githubTokenInput'); if (input) { input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); guardarGithub(); } }); }
  }

  // ---- Atajos de teclado del sistema (capture, para ganarle a Monaco) ----
  function wireShortcuts() {
    documentObject.addEventListener('keydown', function (event) {
      if (!(event.ctrlKey || event.metaKey)) { return; }
      var k = String(event.key).toLowerCase();
      if (event.shiftKey && k === 'e') { event.preventDefault(); toggleExplorer(); }
      else if (event.shiftKey && k === 'n') { event.preventDefault(); newProject(); }
      else if (event.shiftKey && k === 't') { event.preventDefault(); runTestsActive(); }
      else if (event.shiftKey && k === 'x') { event.preventDefault(); clickIf('toggleExtensiones'); }
      else if (!event.shiftKey && k === 'f5') { event.preventDefault(); runActiveFile(); }
      else if (event.key === '`') { event.preventDefault(); clickIf('toggleTerminalWatcher'); }
    }, true);
  }

  // Redimensionado: fuerza el relayout de Monaco al cambiar el tamaño de la
  // ventana de Electron (además del ResizeObserver del adapter, por si acaso).
  var resizeTimer = null;
  function wireResize() {
    root.addEventListener('resize', function () {
      if (resizeTimer) { root.clearTimeout(resizeTimer); }
      resizeTimer = root.setTimeout(function () {
        if (editorAdapter && typeof editorAdapter.layout === 'function') { editorAdapter.layout(); }
      }, 80);
    });
  }

  function inicializar() {
    wireMenubar();
    wireActivityBar();
    wireGithub();
    wireShortcuts();
    wireResize();
    cargarBadges();
    refreshGithub();
    root.setInterval(cargarBadges, 15000);  // el badge de cambios se refresca solo
  }

  // El toast es el único canal de aviso del cromo; lo exponemos para que
  // otros módulos (p. ej. el selector de carpeta) no monten uno propio.
  root.GeramVscodeChrome = { toast: toast };

  if (documentObject.readyState === 'loading') {
    documentObject.addEventListener('DOMContentLoaded', inicializar);
  } else {
    inicializar();
  }
})(typeof window !== 'undefined' ? window : null);
