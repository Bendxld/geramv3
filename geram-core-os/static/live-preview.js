// ============================================================
// GERAM CORE OS · live-preview.js (v3)
// Vista previa en vivo ("Go Live"): split-screen con un iframe sandbox que
// renderiza el archivo web GUARDADO del workspace (ruta /preview/...). El
// iframe se recarga solo al guardar (Ctrl+S) con un cache-buster, para
// mostrar siempre la última versión (limpia la caché del iframe).
// ============================================================
(function (root) {
  'use strict';
  if (!root || !root.document) { return; }
  var documentObject = root.document;
  var $ = function (id) { return documentObject.getElementById(id); };

  var btn = $('livePreviewBtn');
  var pane = $('livePreview');
  var frame = $('livePreviewFrame');
  var titulo = $('livePreviewTitulo');
  if (!btn || !pane || !frame) { return; }

  var previewPath = '';

  function isWeb(path) { return /\.(html?|css|js|mjs|svg|json)$/i.test(path || ''); }

  function previewUrl(path) {
    var encoded = String(path).split('/').map(encodeURIComponent).join('/');
    return '/preview/' + encoded + '?t=' + Date.now();
  }

  function relayoutEditor() {
    var controller = root.GeramWorkspaceController;
    if (controller && controller.editorReady && controller.editorReady.then) {
      controller.editorReady.then(function (adapter) {
        if (adapter && adapter.layout) { root.setTimeout(function () { adapter.layout(); }, 60); }
      }).catch(function () {});
    }
  }

  function abrir() {
    var controller = root.GeramWorkspaceController;
    var path = controller && controller.activePath && controller.activePath();
    if (!path) { titulo.textContent = (window.GeramI18n ? window.GeramI18n.t('lp.openweb') : 'Open a web file to preview it'); }
    if (path && !isWeb(path)) { titulo.textContent = path + ' (no es web)'; }
    previewPath = path || '';
    documentObject.body.classList.add('preview-abierto');
    pane.hidden = false;
    btn.classList.add('activo');
    btn.setAttribute('aria-pressed', 'true');
    if (previewPath) {
      titulo.textContent = previewPath;
      frame.setAttribute('src', previewUrl(previewPath));
    } else {
      frame.removeAttribute('src');
    }
    relayoutEditor();
  }

  function cerrar() {
    documentObject.body.classList.remove('preview-abierto');
    pane.hidden = true;
    btn.classList.remove('activo');
    btn.setAttribute('aria-pressed', 'false');
    frame.removeAttribute('src');
    relayoutEditor();
  }

  function toggle() {
    if (documentObject.body.classList.contains('preview-abierto')) { cerrar(); } else { abrir(); }
  }

  function recargar() {
    var controller = root.GeramWorkspaceController;
    var path = (controller && controller.activePath && controller.activePath()) || previewPath;
    if (!path) { return; }
    previewPath = path;
    titulo.textContent = path;
    frame.setAttribute('src', previewUrl(path));  // nuevo ?t= => sin caché
  }

  btn.addEventListener('click', toggle);
  var cerrarBtn = $('livePreviewCerrar'); if (cerrarBtn) { cerrarBtn.addEventListener('click', cerrar); }
  var reloadBtn = $('livePreviewReload'); if (reloadBtn) { reloadBtn.addEventListener('click', recargar); }

  // Hot-reload: al guardar (Ctrl+S o botón Guardar) recargamos el iframe tras
  // dar tiempo a que el PUT termine.
  function programarRecarga() {
    if (documentObject.body.classList.contains('preview-abierto')) {
      root.setTimeout(recargar, 500);
    }
  }
  documentObject.addEventListener('keydown', function (event) {
    if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 's') { programarRecarga(); }
  }, true);
  var guardarBtn = $('workspaceGuardar');
  if (guardarBtn) { guardarBtn.addEventListener('click', programarRecarga); }

  // Expuesto para el menú de vscode-chrome (View > Go Live).
  root.GeramToggleLivePreview = toggle;
})(typeof window !== 'undefined' ? window : null);
