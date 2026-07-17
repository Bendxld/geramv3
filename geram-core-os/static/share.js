// ============================================================
// GERAM CORE OS · share.js (v3)
// Botón "Compartir" del editor. Dos modos:
//   · Prueba  -> reutiliza el Go Live local (solo tú, localhost).
//   · En línea -> POST /share/start: un mini-server aparte sirve SOLO esta
//     página y devuelve un link LAN (misma WiFi) y, si hay cloudflared, un
//     link público (internet). "Dejar de compartir" -> POST /share/stop.
// El control de compartir es localhost-only en el backend.
// ============================================================
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }

  var btn = $('shareBtn');
  var modal = $('shareModal');
  if (!btn || !modal) { return; }

  var modos = $('shareModos');
  var online = $('shareOnline');
  var estado = $('shareEstado');
  var lanRow = $('shareLinkLanRow');
  var pubRow = $('shareLinkPubRow');
  var lanInput = $('shareLinkLan');
  var pubInput = $('shareLinkPub');
  var lanQr = $('shareQrLan');
  var pubQr = $('shareQrPub');
  var pubNota = $('sharePubNota');
  var archivoLbl = $('shareArchivo');

  // Ruta del archivo activo (workspace-relative), vía el controlador del workspace.
  function activePath() {
    var c = window.GeramWorkspaceController;
    return (c && c.activePath && c.activePath()) || '';
  }

  function esWeb(path) { return /\.html?$/i.test(path || ''); }

  function abrirModal() {
    modal.setAttribute('aria-hidden', 'false');
    modal.classList.add('activo');
  }
  function cerrarModal() {
    modal.setAttribute('aria-hidden', 'true');
    modal.classList.remove('activo');
  }

  // Muestra el paso "elegir modo" o el paso "sesión en línea".
  function mostrarModos() { modos.hidden = false; online.hidden = true; }
  function mostrarOnline() { modos.hidden = true; online.hidden = false; }

  function pintarEstado(data) {
    var hayLan = data && data.lan_url;
    var hayPub = data && data.public_url;

    lanRow.hidden = !hayLan;
    if (hayLan) { lanInput.value = data.lan_url; }
    if (lanQr) {
      if (hayLan && data.lan_qr) { lanQr.src = data.lan_qr; lanQr.hidden = false; }
      else { lanQr.removeAttribute('src'); lanQr.hidden = true; }
    }

    pubRow.hidden = !hayPub;
    if (hayPub) { pubInput.value = data.public_url; }
    if (pubQr) {
      if (hayPub && data.public_qr) { pubQr.src = data.public_qr; pubQr.hidden = false; }
      else { pubQr.removeAttribute('src'); pubQr.hidden = true; }
    }

    // Nota cuando se pidió túnel pero no salió (sin cloudflared o falló).
    var pedidoSinPublico = data && data.tunnel_requested && !hayPub;
    pubNota.hidden = !pedidoSinPublico;

    if (hayLan || hayPub) {
      estado.textContent = 'Sharing “' + (data.file || '') + '”. It stops when you close the app or click “Stop sharing”.';
    }
  }

  function api(url, opts) {
    return fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts))
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          if (!r.ok) {
            var msg = (body && body.detail && body.detail.message) || ('Error ' + r.status);
            throw new Error(msg);
          }
          return body;
        });
      });
  }

  // ------------------------------------------------------------- acciones
  btn.addEventListener('click', function () {
    var path = activePath();
    if (!path) { alert('Open a page in the editor first.'); return; }
    if (!esWeb(path)) { alert('Only a web page (.html) can be shared.'); return; }
    archivoLbl.textContent = path;

    // Si ya hay una sesión activa, muestra directamente el paso en línea.
    api('/share/status', { method: 'GET' }).then(function (data) {
      if (data && data.active) { mostrarOnline(); pintarEstado(data); }
      else { mostrarModos(); }
      abrirModal();
    }).catch(function () { mostrarModos(); abrirModal(); });
  });

  $('shareCerrar').addEventListener('click', cerrarModal);
  modal.addEventListener('click', function (e) { if (e.target === modal) { cerrarModal(); } });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal.classList.contains('activo')) { cerrarModal(); }
  });

  // Modo prueba: reutiliza el Go Live local (localhost).
  $('shareModoPrueba').addEventListener('click', function () {
    cerrarModal();
    var live = $('livePreviewBtn');
    if (live && !document.body.classList.contains('preview-abierto')) { live.click(); }
  });

  // Modo en línea: arranca el mini-server (LAN + túnel si hay).
  $('shareModoEnLinea').addEventListener('click', function () {
    var path = activePath();
    mostrarOnline();
    lanRow.hidden = true; pubRow.hidden = true; pubNota.hidden = true;
    estado.textContent = 'Starting… (the public tunnel may take a few seconds)';
    api('/share/start', { method: 'POST', body: JSON.stringify({ path: path, tunnel: true }) })
      .then(pintarEstado)
      .catch(function (err) {
        estado.textContent = 'Could not share: ' + err.message;
      });
  });

  // Dejar de compartir.
  $('shareStop').addEventListener('click', function () {
    estado.textContent = 'Stopping…';
    api('/share/stop', { method: 'POST' }).then(function () {
      mostrarModos();
    }).catch(function () { mostrarModos(); });
  });

  // Copiar links.
  modal.addEventListener('click', function (e) {
    var copyBtn = e.target.closest ? e.target.closest('.share-copy') : null;
    if (!copyBtn) { return; }
    var input = $(copyBtn.getAttribute('data-copy'));
    if (!input || !input.value) { return; }
    var done = function () {
      var prev = copyBtn.textContent;
      copyBtn.textContent = 'Copied!';
      setTimeout(function () { copyBtn.textContent = prev; }, 1200);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(input.value).then(done, function () { input.select(); document.execCommand('copy'); done(); });
    } else {
      input.select(); document.execCommand('copy'); done();
    }
  });
})();
