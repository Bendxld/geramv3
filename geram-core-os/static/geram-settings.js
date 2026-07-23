// ============================================================
// GERAM CORE OS · geram-settings.js (v3, Paso 2)
// Panel "Configuración de GERAM": perfil, identidad del núcleo,
// paleta de colores, rutas bloqueadas y notificaciones por voz.
// Lee/escribe el config local vía GET/POST /api/config. Todo el
// render usa textContent (sin innerHTML) para no inyectar HTML.
// ============================================================
(function (windowObject, documentObject) {
  'use strict';

  var $ = function (id) { return documentObject.getElementById(id); };

  // Mapa color-de-config -> variable CSS del HUD, para aplicar el tema en vivo.
  var CSS_VARS = {
    primary_color: '--principal',
    background_color: '--fondo',
    accent_color: '--principal-med'
  };

  // Estado local de la lista de rutas bloqueadas (se edita antes de guardar).
  var blockedPaths = [];
  var onboardingState = { manual_version_seen: 0, setup_version_seen: 0 };
  var developerMode = false;
  var loading = false;

  function aplicarTema(theme) {
    if (!theme) { return; }
    var raiz = documentObject.documentElement;
    Object.keys(CSS_VARS).forEach(function (clave) {
      if (theme[clave]) { raiz.style.setProperty(CSS_VARS[clave], theme[clave]); }
    });
  }

  function setEstado(mensaje, esError) {
    var el = $('gsEstado');
    if (!el) { return; }
    el.textContent = mensaje || '';
    el.classList.toggle('error', Boolean(esError));
  }

  function renderBlocked() {
    var lista = $('gsBlockedList');
    if (!lista) { return; }
    lista.textContent = '';
    blockedPaths.forEach(function (ruta, indice) {
      var item = documentObject.createElement('li');
      var texto = documentObject.createElement('span');
      texto.textContent = ruta;
      var quitar = documentObject.createElement('button');
      quitar.type = 'button';
      quitar.className = 'gs-blocked-remove';
      quitar.textContent = '×';
      quitar.setAttribute('aria-label', 'Remove ' + ruta);
      quitar.addEventListener('click', function () {
        blockedPaths.splice(indice, 1);
        renderBlocked();
      });
      item.appendChild(texto);
      item.appendChild(quitar);
      lista.appendChild(item);
    });
  }

  function poblarFormulario(config) {
    var perfil = config.user_profile || {};
    var tema = config.ui_theme || {};
    var privacidad = config.privacy_controls || {};

    $('gsName').value = perfil.name || '';
    $('gsAge').value = (perfil.age === null || perfil.age === undefined) ? '' : perfil.age;
    $('gsPrompt').value = perfil.system_prompt_override || '';
    $('gsLanguage').value = perfil.language || 'auto';
    $('gsTts').checked = Boolean(perfil.use_tts_notifications);

    $('gsIdentity').value = tema.core_identity_view || 'core';
    $('gsPrimary').value = tema.primary_color || '#e84393';
    $('gsBackground').value = tema.background_color || '#0a0a0f';
    $('gsAccent').value = tema.accent_color || '#8d1f68';

    blockedPaths = Array.isArray(privacidad.blocked_paths) ? privacidad.blocked_paths.slice() : [];
    onboardingState = config.onboarding || onboardingState;
    developerMode = Boolean(privacidad.developer_mode);
    renderBlocked();
    aplicarTema(tema);
  }

  function leerFormulario() {
    var edadTexto = $('gsAge').value.trim();
    return {
      user_profile: {
        name: $('gsName').value.trim(),
        age: edadTexto === '' ? null : parseInt(edadTexto, 10),
        system_prompt_override: $('gsPrompt').value,
        language: $('gsLanguage').value,
        use_tts_notifications: $('gsTts').checked
      },
      ui_theme: {
        primary_color: $('gsPrimary').value,
        background_color: $('gsBackground').value,
        accent_color: $('gsAccent').value,
        core_identity_view: $('gsIdentity').value
      },
      privacy_controls: {
        blocked_paths: blockedPaths.slice(),
        developer_mode: developerMode
      },
      onboarding: onboardingState
    };
  }

  function maintenanceStatus(value) {
    var output = $('gsMaintenanceStatus');
    if (output) { output.textContent = value || ''; }
  }

  function cargarBackups() {
    return windowObject.fetch('/api/maintenance/backups', { cache: 'no-store' })
      .then(function (response) { if (!response.ok) { throw new Error('HTTP ' + response.status); } return response.json(); })
      .then(function (payload) {
        var select = $('gsBackupList');
        if (!select) { return; }
        select.textContent = '';
        (payload.backups || []).forEach(function (backup) {
          var option = documentObject.createElement('option');
          option.value = backup.id;
          option.textContent = String(backup.created_at || backup.id) + ' · ' + String(backup.label || 'manual') + ' · ' + Number(backup.files || 0) + ' files';
          select.appendChild(option);
        });
        if (!select.options.length) {
          var empty = documentObject.createElement('option');
          empty.value = ''; empty.textContent = 'No backups yet'; select.appendChild(empty);
        }
      })
      .catch(function (error) { maintenanceStatus('Backups unavailable: ' + error.message); });
  }

  function diagnosticar() {
    maintenanceStatus('Running local diagnostic…');
    windowObject.fetch('/api/maintenance/diagnostics', { cache: 'no-store' })
      .then(function (response) { if (!response.ok) { throw new Error('HTTP ' + response.status); } return response.json(); })
      .then(function (payload) { maintenanceStatus(JSON.stringify(payload, null, 2)); })
      .catch(function (error) { maintenanceStatus('Diagnostic failed: ' + error.message); });
  }

  function crearBackup() {
    maintenanceStatus('Creating portable backup…');
    windowObject.fetch('/api/maintenance/backups', { method: 'POST' })
      .then(function (response) { if (!response.ok) { throw new Error('HTTP ' + response.status); } return response.json(); })
      .then(function (payload) { maintenanceStatus('Backup created: ' + payload.backup.id); return cargarBackups(); })
      .catch(function (error) { maintenanceStatus('Backup failed: ' + error.message); });
  }

  function restaurarBackup() {
    var select = $('gsBackupList');
    var backupId = select ? select.value : '';
    if (!backupId) { maintenanceStatus('Select a backup first.'); return; }
    if (!windowObject.confirm(windowObject.GeramI18n ? windowObject.GeramI18n.t('gs.confirmrestore') : 'Restore portable state from this backup?')) { return; }
    maintenanceStatus('Validating and restoring backup…');
    windowObject.fetch('/api/maintenance/restore', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backup_id: backupId, confirm: 'RESTORE' })
    }).then(function (response) { if (!response.ok) { throw new Error('HTTP ' + response.status); } return response.json(); })
      .then(function (payload) { maintenanceStatus('Restored. Safety backup: ' + payload.safety_backup + '. Restart GERAM to reload every service.'); })
      .catch(function (error) { maintenanceStatus('Restore failed: ' + error.message); });
  }

  function cargar() {
    if (loading) { return; }
    loading = true;
    setEstado('Loading…', false);
    windowObject.fetch('/api/config', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); })
      .then(function (config) { poblarFormulario(config); setEstado('', false); })
      .catch(function (err) { setEstado('Settings could not be loaded: ' + err.message, true); })
      .then(function () { loading = false; });
  }

  function guardar() {
    var payload = leerFormulario();
    setEstado('Saving…', false);
    windowObject.fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
      })
      .then(function (res) {
        if (!res.ok) {
          var detalle = res.data && res.data.detail ? JSON.stringify(res.data.detail) : ('HTTP ' + res.status);
          throw new Error(detalle);
        }
        aplicarTema(res.data.config ? res.data.config.ui_theme : payload.ui_theme);
        setEstado('Guardado.', false);
      })
      .catch(function (err) { setEstado('Could not save: ' + err.message, true); });
  }

  function inicializar() {
    var guardarBtn = $('gsGuardar');
    if (guardarBtn) { guardarBtn.addEventListener('click', guardar); }
    var addBtn = $('gsBlockedAdd');
    var addInput = $('gsBlockedInput');
    if (addBtn && addInput) {
      var agregar = function () {
        var ruta = addInput.value.trim();
        if (ruta && blockedPaths.indexOf(ruta) === -1) {
          blockedPaths.push(ruta);
          renderBlocked();
        }
        addInput.value = '';
        addInput.focus();
      };
      addBtn.addEventListener('click', agregar);
      addInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); agregar(); }
      });
    }
    // Vista previa en vivo del tema mientras se ajustan los colores.
    ['gsPrimary', 'gsBackground', 'gsAccent'].forEach(function (id) {
      var input = $(id);
      if (input) { input.addEventListener('input', function () { aplicarTema(leerFormulario().ui_theme); }); }
    });
    if ($('gsDiagnostic')) { $('gsDiagnostic').addEventListener('click', diagnosticar); }
    if ($('gsBackup')) { $('gsBackup').addEventListener('click', crearBackup); }
    if ($('gsBackupRefresh')) { $('gsBackupRefresh').addEventListener('click', cargarBackups); }
    if ($('gsRestore')) { $('gsRestore').addEventListener('click', restaurarBackup); }
    cargarBackups();
  }

  // The unified Settings panel owns navigation and visibility. This module
  // only owns the personal-settings form and exposes a small integration API.
  windowObject.GeramSettings = { load: cargar, save: guardar, applyTheme: aplicarTema };

  if (documentObject.readyState === 'loading') {
    documentObject.addEventListener('DOMContentLoaded', inicializar);
  } else {
    inicializar();
  }
})(window, document);
