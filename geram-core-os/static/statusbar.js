// ============================================================
// GERAM CORE OS · statusbar.js (v3, Paso 3)
// Barra de estado inferior estilo VS Code: rama Git activa, nombre del
// workspace e indicador de Línea/Columna del cursor (leído de Monaco).
// También enciende el banner de "Modo Desarrollador" cuando el backend
// reporta que el workspace es el código interno de GERAM.
// Datos: GET /api/workspace/status. Cero estado persistido.
// ============================================================
(function (root) {
  'use strict';
  if (!root || !root.document) { return; }
  var documentObject = root.document;
  var $ = function (id) { return documentObject.getElementById(id); };

  function setCursor(line, column) {
    var el = $('statusbarCursor');
    if (el) { el.textContent = 'Ln ' + line + ', Col ' + column; }
  }

  function aplicarEstado(status) {
    var branch = status && status.branch ? status.branch : null;
    var nameEl = $('statusbarBranchName');
    var branchEl = $('statusbarBranch');
    if (nameEl) { nameEl.textContent = branch || 'no git'; }
    if (branchEl) { branchEl.classList.toggle('sin-git', !branch); }

    var wsEl = $('statusbarWorkspace');
    if (wsEl && status && status.workspace_name) { wsEl.textContent = status.workspace_name; }

    // Modo desarrollador: banner de advertencia + marca en la status bar.
    var dev = Boolean(status && status.developer_mode);
    var banner = $('devModeBanner');
    if (banner) { banner.hidden = !dev; }
    documentObject.body.classList.toggle('dev-mode-activo', dev);
    var bar = $('statusbar');
    if (bar) { bar.classList.toggle('dev', dev); }
  }

  function cargarEstado() {
    root.fetch('/api/workspace/status', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (status) { if (status) { aplicarEstado(status); } })
      .catch(function () { /* status bar es informativa; no romper el HUD */ });
  }

  // Cursor en vivo desde Monaco (si cargó; con el editor de respaldo no hay
  // posición nativa, se queda en Ln 1, Col 1).
  function engancharCursor() {
    var controller = root.GeramWorkspaceController;
    if (!controller || !controller.editorReady || !controller.editorReady.then) { return; }
    controller.editorReady.then(function (adapter) {
      if (!adapter || !adapter.editor || typeof adapter.editor.onDidChangeCursorPosition !== 'function') { return; }
      adapter.editor.onDidChangeCursorPosition(function (event) {
        setCursor(event.position.lineNumber, event.position.column);
      });
      var pos = adapter.editor.getPosition && adapter.editor.getPosition();
      if (pos) { setCursor(pos.lineNumber, pos.column); }
    }).catch(function () { /* editor no disponible: se deja el valor por defecto */ });
  }

  function inicializar() {
    cargarEstado();
    engancharCursor();
  }

  if (documentObject.readyState === 'loading') {
    documentObject.addEventListener('DOMContentLoaded', inicializar);
  } else {
    inicializar();
  }
})(typeof window !== 'undefined' ? window : null);
