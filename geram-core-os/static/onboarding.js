(function (root) {
  'use strict';

  // 2: the first run now introduces the two roles before the readiness checks,
  // so installations that only saw the checks get it once more.
  var SETUP_VERSION = 2;
  var documentObject = root.document;
  var currentConfig = null;

  function byId(id) { return documentObject.getElementById(id); }
  function setText(id, value) { var node = byId(id); if (node) { node.textContent = value; } }
  // Traducción de los textos generados en JS (los estáticos van por data-i18n).
  function T(key, fallback) {
    return (root.GeramI18n && root.GeramI18n.t) ? root.GeramI18n.t(key) : fallback;
  }
  function shouldOpen(config) {
    var seen = config && config.onboarding && Number(config.onboarding.setup_version_seen || 0);
    return seen < SETUP_VERSION;
  }
  function show() {
    var modal = byId('setupModal');
    if (!modal) { return; }
    modal.classList.add('activo');
    modal.setAttribute('aria-hidden', 'false');
  }
  function hide() {
    var modal = byId('setupModal');
    if (!modal) { return; }
    modal.classList.remove('activo');
    modal.setAttribute('aria-hidden', 'true');
  }
  function ready(value) { return value ? T('setup.ready', 'READY') : T('setup.notready', 'NOT READY'); }
  function applyStatus(status) {
    var platform = status.platform || {};
    var dependencies = platform.dependencies || {};
    var roles = status.roles || {};
    setText('setupPlatform', String(platform.os || 'unknown').toUpperCase() +
      (platform.deployment === 'wsl2' ? ' · WSL2' : ' · NATIVE'));
    setText('setupSandbox', ready(dependencies.sandbox));
    setText('setupIris', ready(roles.iris && roles.iris.configured));
    setText('setupAres', ready(roles.ares && roles.ares.configured));
    setText('setupOllama', ready(status.ollama_available));
    setText('setupPdf', ready(dependencies.pdf_text));
  }
  function refreshStatus() {
    return root.fetch('/api/runtime/status', { cache: 'no-store' })
      .then(function (response) { if (!response.ok) { throw new Error('status'); } return response.json(); })
      .then(applyStatus)
      .catch(function () {
        ['setupPlatform', 'setupSandbox', 'setupIris', 'setupAres', 'setupOllama', 'setupPdf']
          .forEach(function (id) { setText(id, T('setup.unavailable', 'UNAVAILABLE')); });
      });
  }
  function testMedia(kind) {
    var sufijo = kind === 'microphone' ? 'mic' : 'cam';
    if (!root.navigator.mediaDevices || !root.navigator.mediaDevices.getUserMedia) {
      setText('setupMediaStatus', T('setup.media.unavailable', 'Media devices are unavailable in this environment.'));
      return Promise.resolve(false);
    }
    setText('setupMediaStatus', T('setup.media.requesting.' + sufijo, 'Requesting ' + kind + ' permission…'));
    var constraints = kind === 'microphone' ? { audio: true } : { video: true };
    return root.navigator.mediaDevices.getUserMedia(constraints)
      .then(function (stream) {
        stream.getTracks().forEach(function (track) { track.stop(); });
        setText('setupMediaStatus', T('setup.media.ready.' + sufijo, kind + ' is ready; the test stream was stopped.'));
        return true;
      })
      .catch(function () {
        setText('setupMediaStatus', T('setup.media.denied.' + sufijo, kind + ' permission was not granted or no device is available.'));
        return false;
      });
  }
  function finish() {
    if (!currentConfig) { return; }
    var name = String((byId('setupName') && byId('setupName').value) || '').trim();
    if (name) { currentConfig.user_profile.name = name; }
    // currentConfig se leyó al arrancar, ANTES de que el selector de idioma
    // guardara la elección; sin esto, este POST la pisaría con el valor viejo.
    if (root.GeramI18n && root.GeramI18n.hasChoice && root.GeramI18n.hasChoice()) {
      currentConfig.user_profile.language = root.GeramI18n.current();
    }
    setText('setupSaveStatus', T('setup.saving', 'Saving local setup…'));
    root.fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentConfig),
    }).then(function (response) {
      if (!response.ok) { throw new Error('config'); }
      return root.fetch('/api/config/setup-complete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: SETUP_VERSION }),
      });
    }).then(function (response) {
      if (!response.ok) { throw new Error('setup'); }
      hide();
      if (root.GeramRuntimeStatus) { root.GeramRuntimeStatus.refresh(); }
    }).catch(function () { setText('setupSaveStatus', T('setup.savefail', 'Setup could not be saved.')); });
  }
  function bind() {
    var refresh = byId('setupRefresh');
    var settings = byId('setupSettings');
    var mic = byId('setupTestMic');
    var camera = byId('setupTestCamera');
    var finishButton = byId('setupFinish');
    var later = byId('setupLater');
    if (refresh) { refresh.addEventListener('click', refreshStatus); }
    if (settings) { settings.addEventListener('click', function () { hide(); var button = byId('toggleConfig'); if (button) { button.click(); } }); }
    if (mic) { mic.addEventListener('click', function () { testMedia('microphone'); }); }
    if (camera) { camera.addEventListener('click', function () { testMedia('camera'); }); }
    if (finishButton) { finishButton.addEventListener('click', finish); }
    if (later) { later.addEventListener('click', hide); }
  }
  function start() {
    bind();
    root.fetch('/api/config', { cache: 'no-store' })
      .then(function (response) { if (!response.ok) { throw new Error('config'); } return response.json(); })
      .then(function (config) {
        currentConfig = config;
        var input = byId('setupName');
        if (input) { input.value = String((config.user_profile && config.user_profile.name) || ''); }
        if (shouldOpen(config)) { show(); refreshStatus(); }
      }).catch(function () { /* the normal settings surface remains available */ });
  }

  root.GeramOnboarding = { version: SETUP_VERSION, shouldOpen: shouldOpen, applyStatus: applyStatus, start: start };
  start();
})(window);
