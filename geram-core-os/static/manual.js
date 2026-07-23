(function(root, factory) {
  'use strict';
  var api = factory(root || {});
  if (typeof module === 'object' && module.exports) { module.exports = api; }
  if (root) { root.GeramManual = api; }
})(typeof window !== 'undefined' ? window : globalThis, function(root) {
  'use strict';

  var MANUAL_VERSION = 1;
  var documentObject = root.document;
  var dismissedThisSession = false;

  function shouldOpen(config, version) {
    var seen = config && config.onboarding &&
      Number.isInteger(config.onboarding.manual_version_seen) ?
      config.onboarding.manual_version_seen : 0;
    return seen === 0;
  }

  if (!documentObject) {
    return { version: MANUAL_VERSION, shouldOpen: shouldOpen };
  }

  var modal = documentObject.getElementById('manualModal');
  var closeButton = documentObject.getElementById('manualClose');
  var doneButton = documentObject.getElementById('manualDone');
  var backdrop = documentObject.getElementById('manualBackdrop');
  var title = documentObject.getElementById('manualTitle');
  var eyebrow = documentObject.getElementById('manualEyebrow');
  var status = documentObject.getElementById('manualStatus');
  var activeRole = 'iris';

  function markSeen() {
    if (typeof root.fetch !== 'function') { return; }
    root.fetch('/api/config/manual-seen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: MANUAL_VERSION }),
      keepalive: true
    }).catch(function() {});
  }

  function selectRole(role) {
    activeRole = role === 'ares' ? 'ares' : 'iris';
    documentObject.querySelectorAll('[data-manual-panel]').forEach(function(panel) {
      panel.hidden = panel.getAttribute('data-manual-panel') !== activeRole;
    });
    documentObject.querySelectorAll('[data-manual-role]').forEach(function(button) {
      var selected = button.getAttribute('data-manual-role') === activeRole;
      button.classList.toggle('activo', selected);
      button.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    var t = (root.GeramI18n && root.GeramI18n.t) || function(key) { return key; };
    if (activeRole === 'ares') {
      if (eyebrow) { eyebrow.textContent = t('manual.ares.eyebrow'); }
      if (title) { title.textContent = t('manual.ares.title'); }
      if (status) { status.textContent = t('manual.status.ares'); }
    } else {
      if (eyebrow) { eyebrow.textContent = t('manual.eyebrow'); }
      if (title) { title.textContent = t('manual.title'); }
      if (status) { status.textContent = t('manual.status.iris'); }
    }
    var panel = documentObject.querySelector('[data-manual-panel="' + activeRole + '"]');
    var panelContent = panel && panel.querySelector('.manual-content');
    if (panelContent) { panelContent.scrollTop = 0; }
  }

  function open(role) {
    if (!modal) { return; }
    selectRole(role || activeRole);
    modal.classList.add('activo');
    modal.setAttribute('aria-hidden', 'false');
    if (closeButton) { closeButton.focus(); }
  }

  function close() {
    if (!modal || !modal.classList.contains('activo')) { return; }
    dismissedThisSession = true;
    modal.classList.remove('activo');
    modal.setAttribute('aria-hidden', 'true');
    markSeen();
  }

  function wire() {
    if (!modal) { return; }
    if (closeButton) { closeButton.addEventListener('click', close); }
    if (doneButton) { doneButton.addEventListener('click', close); }
    if (backdrop) { backdrop.addEventListener('click', close); }
    documentObject.querySelectorAll('[data-manual-role]').forEach(function(button) {
      button.addEventListener('click', function() {
        selectRole(button.getAttribute('data-manual-role'));
      });
    });
    documentObject.querySelectorAll('[data-manual-target]').forEach(function(button) {
      button.addEventListener('click', function() {
        var section = documentObject.getElementById(button.getAttribute('data-manual-target'));
        if (section && typeof section.scrollIntoView === 'function') {
          section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    });
    documentObject.addEventListener('keydown', function(event) {
      if (event.key === 'Escape' && modal.classList.contains('activo')) { close(); }
    });

    if (typeof root.fetch !== 'function') { open('iris'); return; }
    root.fetch('/api/config', { cache: 'no-store' })
      .then(function(response) {
        if (!response.ok) { throw new Error('manual_config_unavailable'); }
        return response.json();
      })
      .then(function(config) {
        if (!dismissedThisSession && shouldOpen(config, MANUAL_VERSION)) { open('iris'); }
      })
      .catch(function() {
        if (!dismissedThisSession) { open('iris'); }
      });
  }

  wire();
  return {
    version: MANUAL_VERSION,
    shouldOpen: shouldOpen,
    open: open,
    selectRole: selectRole,
    close: close
  };
});
