// Real startup/status controller. No random health claims are generated here.
(function (root) {
  'use strict';

  var documentObject = root.document;

  function byId(id) { return documentObject.getElementById(id); }
  function log(message) {
    if (typeof root.geramLog === 'function') { root.geramLog(message); }
  }
  function yesNo(value) { return value ? 'READY' : 'UNAVAILABLE'; }

  function applyState(state) {
    var voice = byId('btn-voz');
    var vision = byId('btn-vista');
    if (voice) { voice.classList.toggle('activo', state.voice_enabled === true); }
    if (vision) { vision.classList.toggle('activo', state.vision_enabled === true); }
    root.vozActiva = state.voice_enabled === true;
  }

  function bootLines(status) {
    var integrations = status.integrations || [];
    var connected = integrations.filter(function (item) { return item.state === 'connected'; });
    var iris = (status.roles && status.roles.iris) || {};
    var ares = (status.roles && status.roles.ares) || {};
    var media = status.media || {};
    var agents = status.agents || {};
    return [
      'STARTING GERAM CORE OS v3 ...',
      'LOCAL BACKEND ................. ONLINE',
      'REAL TELEMETRY ................ READY',
      'I.R.I.S. PROVIDER · ' + String(iris.provider || 'none').toUpperCase() + ' ... ' + yesNo(iris.configured),
      'A.R.E.S. PROVIDER · ' + String(ares.provider || 'none').toUpperCase() + ' ... ' + yesNo(ares.configured),
      'OLLAMA LOCAL SERVICE .......... ' + yesNo(status.ollama_available),
      'INTEGRATIONS CONNECTED ........ ' + connected.length + '/' + integrations.length,
      'AGENTS ENABLED ................ ' + Number(agents.enabled || 0) + '/' + Number(agents.total || 0),
      'PDF TEXT READER ............... ' + yesNo(media.pdf_text),
      'AUDIO TRANSCRIPTION ........... ' + yesNo(media.local_whisper || media.provider_audio),
      'BROWSER SPEECH ................ ' + yesNo(media.browser_tts),
      '',
      'GERAM UI READY'
    ];
  }

  function runBoot(lines) {
    var boot = byId('boot');
    var output = byId('bootLog');
    if (!boot || !output) { return; }
    output.textContent = '';
    var index = 0;
    var timer = root.setInterval(function () {
      output.textContent += '> ' + lines[index] + '\n';
      index += 1;
      if (index < lines.length) { return; }
      root.clearInterval(timer);
      root.setTimeout(function () {
        boot.classList.add('fuera');
        documentObject.body.classList.add('listo');
        if (typeof root.intentarFullscreenTV === 'function') { root.intentarFullscreenTV(); }
      }, 350);
    }, 90);
  }

  function applyStatus(status) {
    applyState(status.state || {});
    var summary = byId('runtimeUserSummary');
    if (summary) {
      summary.textContent = 'USER: ' + String((status.user && status.user.name) || 'Local user').toUpperCase() +
        ' · DATA: PRIVATE LOCAL PROFILE';
    }
    var pill = documentObject.querySelector('.estado-pill');
    if (pill) {
      pill.lastChild.textContent = 'SYSTEM ONLINE · REAL DATA';
    }
    var ring = byId('anilloAgentes');
    if (ring) {
      var connected = (status.integrations || []).filter(function (item) {
        return item.state === 'connected';
      }).length;
      var agents = status.agents || {};
      ring.textContent = 'GERAM OS v3 · USER ' +
        String((status.user && status.user.name) || 'LOCAL').toUpperCase() +
        ' · AGENTS ' + Number(agents.enabled || 0) + '/' + Number(agents.total || 0) +
        ' · INTEGRATIONS ' + connected + '/' + (status.integrations || []).length +
        ' · LOCAL PROFILE · ';
    }
    (status.integrations || []).forEach(function (item) {
      log('INTEGRATION ' + String(item.name || item.id).toUpperCase() + ': ' + String(item.state || 'available').toUpperCase());
    });
    log('AGENTS: ' + status.agents.enabled + '/' + status.agents.total + ' ENABLED FOR THIS USER');
  }

  function refresh() {
    return root.fetch('/api/runtime/status', { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) { throw new Error('HTTP ' + response.status); }
        return response.json();
      })
      .then(function (status) {
        applyStatus(status);
        runBoot(bootLines(status));
        if (typeof root.cargarInfo === 'function') { root.cargarInfo(); }
        return status;
      })
      .catch(function () {
        runBoot([
          'STARTING GERAM CORE OS v3 ...',
          'LOCAL BACKEND STATUS ........ UNAVAILABLE',
          'NO SERVICE STATUS WAS ASSUMED',
          '',
          'GERAM UI READY · BACKEND OFFLINE'
        ]);
        log('BACKEND STATUS: UNAVAILABLE');
        return null;
      });
  }

  root.GeramRuntimeStatus = { refresh: refresh, applyState: applyState };
  refresh();
})(window);
