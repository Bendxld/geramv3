// ============================================================
// GERAM CORE OS · i18n.js
// Motor de traducción de la interfaz. La elección de idioma se hace en la
// pantalla de arranque (language-gate.js) ANTES del manual, se guarda en
// localStorage ("geram-ui-lang") para el arranque inmediato, y se sincroniza
// con el perfil del usuario (user_profile.language) para que el ASISTENTE
// (IRIS/A.R.E.S.) responda en el mismo idioma.
//
// Uso en el HTML (atributos):
//   data-i18n="clave"        -> textContent
//   data-i18n-html="clave"   -> innerHTML (para textos con <b>/<kbd>)
//   data-i18n-title="clave"  -> title
//   data-i18n-ph="clave"     -> placeholder
//   data-i18n-aria="clave"   -> aria-label
// Uso en JS:  window.GeramI18n.t('clave')
//
// Este primer paso cubre el selector, el setup de primer arranque y el
// mensaje de roles A.R.E.S./I.R.I.S. del manual; el resto de la UI se traduce
// por tandas. Sin traducción para una clave, cae al inglés (idioma base).
// ============================================================
(function (root) {
  'use strict';

  var STORAGE_KEY = 'geram-ui-lang';
  var DEFAULT = 'en';
  var current = DEFAULT;

  var DICT = {
    en: {
      // --- Language gate (bilingual by nature; shown before any choice) ---
      'gate.hint': 'You can change this later in Settings.',
      // --- Top bar ---
      'top.explorer': 'Toggle file explorer',
      'top.workspace': 'Open local workspace',
      'top.settings': 'Settings (AI, integrations, profile and privacy)',
      'top.profile': 'Switch IRIS/A.R.E.S. profile',
      // --- VS Code-style top menu bar ---
      'menu.file': 'File',
      'menu.edit': 'Edit',
      'menu.selection': 'Selection',
      'menu.view': 'View',
      'menu.go': 'Go',
      'menu.run': 'Run',
      'menu.terminal': 'Terminal',
      'menu.help': 'Help',
      // --- IRIS HUD labels / sense buttons ---
      'hud.back': 'BACK',
      'hud.back.title': 'Return to normal view',
      'hud.mic.title': 'Microphone',
      'hud.voice': 'VOICE',
      'hud.voice.title': 'Voice output',
      'hud.vision': 'VISION',
      'hud.vision.title': 'Camera / Vision',
      'hud.energy': 'ENERGY',
      'hud.network': 'NETWORK',
      'hud.coretemp': 'CORE TEMP',
      'hud.uptime': 'UPTIME',
      'hud.status': 'STATUS',
      // --- Editor / workspace chrome (static bits) ---
      'ws.waiting': 'Waiting to load.',
      'ws.nofile': 'No file open',
      'ws.initmonaco': 'Initializing local Monaco Editor...',
      'ws.fallback': 'Fallback editor for the active file',
      'ws.preview': 'Preview',
      'ws.accept': 'Accept',
      'ws.accept.title': 'Accept (Ctrl+Enter)',
      'ws.reject': 'Reject',
      'ws.reject.title': 'Reject (Esc)',
      'ws.problems': 'Problems',
      'ws.golive': '◱ Go Live',
      'ws.golive.title': 'Live preview (Go Live)',
      'ws.share': '⇪ Share',
      'ws.share.title': 'Share this page',
      'ws.reload.title': 'Reload',
      'ws.closepreview': 'Close preview',
      'ws.proposal': 'A.R.E.S. · PROPOSAL',
      'ws.save': 'Save',
      'ws.unsaved': 'UNSAVED CHANGES',
      'ws.confirmswitch': 'There are unsaved changes. Switch files and keep them pending?',
      // --- HUD panel titles ---
      'panel.systemstatus': 'SYSTEM STATUS',
      'panel.console': 'CONSOLE',
      'panel.chronometry': 'CHRONOMETRY',
      'panel.voice': 'VOICE ANALYSIS',
      'panel.agents': 'AGENTS AND SKILLS',
      'panel.workspace': 'LOCAL WORKSPACE',
      'panel.files': 'FILES',
      'panel.ares.proposal': 'A.R.E.S. · REVIEWABLE PROPOSAL',
      'panel.ares.explain': 'A.R.E.S. · EXPLAIN CODE',
      // --- Settings modal (static parts; the AI-provider sidebar is dynamic) ---
      'settings.title': 'SETTINGS',
      'settings.close': 'Close settings',
      'settings.save': 'Save and restart',
      'gs.profile': 'Profile',
      'gs.name': 'Name',
      'gs.age': 'Age',
      'gs.prompt': 'Global personalization prompt',
      'gs.prompt.ph': "I'm a developer; adapt explanations to my preferences...",
      'gs.language': 'Assistant language',
      'gs.lang.auto': 'Auto (match my message)',
      'gs.tts': 'Voice notifications (TTS)',
      'gs.identity': 'Core identity',
      'gs.coreview': 'Core view',
      'gs.core.core': 'Animated core',
      'gs.core.pet': 'Pet',
      'gs.core.minimal': 'Minimal',
      'gs.palette': 'Color palette',
      'gs.primary': 'Primary color',
      'gs.background': 'Background color',
      'gs.accent': 'Accent color',
      'gs.privacy': 'Privacy · blocked paths',
      'gs.blocked.label': 'Add a path or name (e.g. .env)',
      'gs.add': 'Add',
      'gs.backup.legend': 'Backup, recovery, and diagnostics',
      'gs.backup.p': 'Portable state includes profile, runtime switches, agent state, custom skills/agents, and declarative extensions. Credentials, tokens, pending media, and workspace files are excluded.',
      'gs.diagnostic': 'Run local diagnostic',
      'gs.backup.create': 'Create backup',
      'gs.backup.refresh': 'Refresh backups',
      'gs.restore': 'Restore selected backup',
      'gs.backuplist.aria': 'Available local backups',
      'gs.save': 'Save personal settings',
      // --- First-run setup ---
      'setup.eyebrow': 'GERAM CORE OS · FIRST RUN',
      'setup.title': 'Welcome to GERAM CORE OS',
      'setup.subtitle': 'Everything below runs on this machine. Credentials live in Settings and are never shown here.',
      'setup.whatis.h': 'What this is',
      'setup.whatis.p': 'A local development environment with two assistants sharing one window.',
      'setup.role.ares.d': 'Works in your workspace: Monaco editor, file explorer, terminal, source control. It proposes a diff you review and approve — it never edits on its own.',
      'setup.role.iris.d': 'The conversational assistant: voice, reminders, calendar, and the rest of the agents. Optional — the editor works without it.',
      'setup.steps': 'To get going: <b>1)</b> add an AI provider key in Settings, <b>2)</b> open a folder as your workspace, <b>3)</b> press <kbd>Ctrl</kbd>+<kbd>S</kbd> to save, like any editor. The full manual is always one click away in the top bar.',
      'setup.s1.h': 'Your local profile',
      'setup.name.label': 'Display name',
      'setup.name.ph': 'Local user',
      'setup.s1.p': 'This profile and the runtime switches belong only to the current operating-system user.',
      'setup.s2.h': 'System readiness',
      'setup.platform': 'Platform',
      'setup.runner': 'Secure runner',
      'setup.pdf': 'PDF reader',
      'setup.checkagain': 'Check again',
      'setup.openprovider': 'Open provider settings',
      'setup.s3.h': 'Optional local permissions',
      'setup.s3.p': 'Permission is requested only when you press a test button. The stream is stopped immediately.',
      'setup.testmic': 'Test microphone',
      'setup.testcam': 'Test camera',
      'setup.nottested': 'Not tested.',
      'setup.later': 'Later',
      'setup.saveandstart': 'Save and start',
      // setup dynamic (onboarding.js)
      'setup.checking': 'Checking…',
      'setup.ready': 'READY',
      'setup.notready': 'NOT READY',
      'setup.unavailable': 'UNAVAILABLE',
      'setup.saving': 'Saving local setup…',
      'setup.savefail': 'Setup could not be saved.',
      'setup.media.unavailable': 'Media devices are unavailable in this environment.',
      'setup.media.requesting.mic': 'Requesting microphone permission…',
      'setup.media.requesting.cam': 'Requesting camera permission…',
      'setup.media.ready.mic': 'microphone is ready; the test stream was stopped.',
      'setup.media.ready.cam': 'camera is ready; the test stream was stopped.',
      'setup.media.denied.mic': 'microphone permission was not granted or no device is available.',
      'setup.media.denied.cam': 'camera permission was not granted or no device is available.',
      // --- Manual (header, tabs, nav, role intro) ---
      'manual.eyebrow': 'I.R.I.S. · ADAPTED USER MANUAL',
      'manual.title': 'Everything you can ask I.R.I.S. to do',
      'manual.close': 'Close manual',
      'manual.tab.iris': 'I.R.I.S. Manual',
      'manual.tab.ares': 'A.R.E.S. Manual',
      'manual.nav.start': 'Meet I.R.I.S.',
      'manual.nav.chat': 'Chat and help',
      'manual.nav.control': 'Voice and camera',
      'manual.nav.files': 'Files and agents',
      'manual.nav.editor': 'Developer workspace',
      'manual.nav.connections': 'Plans and connections',
      'manual.nav.safety': 'Security and offline',
      'manual.start.h': 'Meet I.R.I.S.',
      'manual.start.p': "I.R.I.S. is GERAM's conversational assistant: direct, witty, and built for everyday help. A.R.E.S. is the professional coding role. Both now live inside GERAM CORE OS and can use the AI provider you choose in Settings.",
      'manual.start.callout.t': 'Talk naturally',
      'manual.start.callout.d': 'Ask a question or say “system status.” I.R.I.S. answers in the language you use and receives real CPU/RAM data for hardware-status questions.'
    },
    es: {
      'gate.hint': 'Puedes cambiarlo luego en Settings.',
      'top.explorer': 'Mostrar/ocultar el explorador de archivos',
      'top.workspace': 'Abrir workspace local',
      'top.settings': 'Ajustes (IA, integraciones, perfil y privacidad)',
      'top.profile': 'Cambiar perfil IRIS/A.R.E.S.',
      'menu.file': 'Archivo',
      'menu.edit': 'Editar',
      'menu.selection': 'Selección',
      'menu.view': 'Ver',
      'menu.go': 'Ir',
      'menu.run': 'Ejecutar',
      'menu.terminal': 'Terminal',
      'menu.help': 'Ayuda',
      'hud.back': 'ATRÁS',
      'hud.back.title': 'Volver a la vista normal',
      'hud.mic.title': 'Micrófono',
      'hud.voice': 'VOZ',
      'hud.voice.title': 'Salida de voz',
      'hud.vision': 'VISIÓN',
      'hud.vision.title': 'Cámara / Visión',
      'hud.energy': 'ENERGÍA',
      'hud.network': 'RED',
      'hud.coretemp': 'TEMP. NÚCLEO',
      'hud.uptime': 'TIEMPO ACTIVO',
      'hud.status': 'ESTADO',
      'ws.waiting': 'Esperando para cargar.',
      'ws.nofile': 'Ningún archivo abierto',
      'ws.initmonaco': 'Inicializando el editor Monaco local...',
      'ws.fallback': 'Editor de respaldo para el archivo activo',
      'ws.preview': 'Vista previa',
      'ws.accept': 'Aceptar',
      'ws.accept.title': 'Aceptar (Ctrl+Enter)',
      'ws.reject': 'Rechazar',
      'ws.reject.title': 'Rechazar (Esc)',
      'ws.problems': 'Problemas',
      'ws.golive': '◱ En vivo',
      'ws.golive.title': 'Vista previa en vivo (Go Live)',
      'ws.share': '⇪ Compartir',
      'ws.share.title': 'Compartir esta página',
      'ws.reload.title': 'Recargar',
      'ws.closepreview': 'Cerrar vista previa',
      'ws.proposal': 'A.R.E.S. · PROPUESTA',
      'ws.save': 'Guardar',
      'ws.unsaved': 'CAMBIOS SIN GUARDAR',
      'ws.confirmswitch': 'Hay cambios sin guardar. ¿Cambiar de archivo y dejarlos pendientes?',
      'panel.systemstatus': 'ESTADO DEL SISTEMA',
      'panel.console': 'CONSOLA',
      'panel.chronometry': 'CRONOMETRÍA',
      'panel.voice': 'ANÁLISIS DE VOZ',
      'panel.agents': 'AGENTES Y SKILLS',
      'panel.workspace': 'WORKSPACE LOCAL',
      'panel.files': 'ARCHIVOS',
      'panel.ares.proposal': 'A.R.E.S. · PROPUESTA REVISABLE',
      'panel.ares.explain': 'A.R.E.S. · EXPLICAR CÓDIGO',
      'settings.title': 'AJUSTES',
      'settings.close': 'Cerrar ajustes',
      'settings.save': 'Guardar y reiniciar',
      'gs.profile': 'Perfil',
      'gs.name': 'Nombre',
      'gs.age': 'Edad',
      'gs.prompt': 'Prompt de personalización global',
      'gs.prompt.ph': 'Soy desarrollador; adapta las explicaciones a mis preferencias...',
      'gs.language': 'Idioma del asistente',
      'gs.lang.auto': 'Auto (según mi mensaje)',
      'gs.tts': 'Notificaciones por voz (TTS)',
      'gs.identity': 'Identidad del núcleo',
      'gs.coreview': 'Vista del núcleo',
      'gs.core.core': 'Núcleo animado',
      'gs.core.pet': 'Mascota',
      'gs.core.minimal': 'Minimal',
      'gs.palette': 'Paleta de colores',
      'gs.primary': 'Color primario',
      'gs.background': 'Color de fondo',
      'gs.accent': 'Color de acento',
      'gs.privacy': 'Privacidad · rutas bloqueadas',
      'gs.blocked.label': 'Agrega una ruta o nombre (ej. .env)',
      'gs.add': 'Agregar',
      'gs.backup.legend': 'Respaldo, recuperación y diagnóstico',
      'gs.backup.p': 'El estado portable incluye perfil, interruptores de runtime, estado de agentes, skills/agentes personalizados y extensiones declarativas. Se excluyen credenciales, tokens, medios pendientes y archivos del workspace.',
      'gs.diagnostic': 'Ejecutar diagnóstico local',
      'gs.backup.create': 'Crear respaldo',
      'gs.backup.refresh': 'Actualizar respaldos',
      'gs.restore': 'Restaurar respaldo seleccionado',
      'gs.backuplist.aria': 'Respaldos locales disponibles',
      'gs.save': 'Guardar ajustes personales',
      'setup.eyebrow': 'GERAM CORE OS · PRIMER ARRANQUE',
      'setup.title': 'Bienvenido a GERAM CORE OS',
      'setup.subtitle': 'Todo lo de abajo corre en esta máquina. Las credenciales viven en Ajustes y nunca se muestran aquí.',
      'setup.whatis.h': 'Qué es esto',
      'setup.whatis.p': 'Un entorno de desarrollo local con dos asistentes compartiendo una ventana.',
      'setup.role.ares.d': 'Trabaja en tu workspace: editor Monaco, explorador de archivos, terminal, control de versiones. Propone un diff que revisas y apruebas — nunca edita por su cuenta.',
      'setup.role.iris.d': 'El asistente conversacional: voz, recordatorios, calendario y el resto de los agentes. Opcional — el editor funciona sin él.',
      'setup.steps': 'Para empezar: <b>1)</b> agrega una clave de proveedor de IA en Ajustes, <b>2)</b> abre una carpeta como tu workspace, <b>3)</b> presiona <kbd>Ctrl</kbd>+<kbd>S</kbd> para guardar, como cualquier editor. El manual completo está siempre a un clic en la barra superior.',
      'setup.s1.h': 'Tu perfil local',
      'setup.name.label': 'Nombre para mostrar',
      'setup.name.ph': 'Usuario local',
      'setup.s1.p': 'Este perfil y los interruptores de runtime pertenecen solo al usuario actual del sistema operativo.',
      'setup.s2.h': 'Estado del sistema',
      'setup.platform': 'Plataforma',
      'setup.runner': 'Runner seguro',
      'setup.pdf': 'Lector de PDF',
      'setup.checkagain': 'Comprobar de nuevo',
      'setup.openprovider': 'Abrir ajustes de proveedores',
      'setup.s3.h': 'Permisos locales opcionales',
      'setup.s3.p': 'El permiso se pide solo cuando presionas un botón de prueba. El stream se detiene de inmediato.',
      'setup.testmic': 'Probar micrófono',
      'setup.testcam': 'Probar cámara',
      'setup.nottested': 'Sin probar.',
      'setup.later': 'Más tarde',
      'setup.saveandstart': 'Guardar y empezar',
      'setup.checking': 'Comprobando…',
      'setup.ready': 'LISTO',
      'setup.notready': 'NO LISTO',
      'setup.unavailable': 'NO DISPONIBLE',
      'setup.saving': 'Guardando setup local…',
      'setup.savefail': 'No se pudo guardar el setup.',
      'setup.media.unavailable': 'Los dispositivos multimedia no están disponibles en este entorno.',
      'setup.media.requesting.mic': 'Pidiendo permiso de micrófono…',
      'setup.media.requesting.cam': 'Pidiendo permiso de cámara…',
      'setup.media.ready.mic': 'el micrófono está listo; el stream de prueba se detuvo.',
      'setup.media.ready.cam': 'la cámara está lista; el stream de prueba se detuvo.',
      'setup.media.denied.mic': 'no se concedió el permiso de micrófono o no hay dispositivo disponible.',
      'setup.media.denied.cam': 'no se concedió el permiso de cámara o no hay dispositivo disponible.',
      'manual.eyebrow': 'I.R.I.S. · MANUAL DE USUARIO ADAPTADO',
      'manual.title': 'Todo lo que puedes pedirle a I.R.I.S.',
      'manual.close': 'Cerrar manual',
      'manual.tab.iris': 'Manual de I.R.I.S.',
      'manual.tab.ares': 'Manual de A.R.E.S.',
      'manual.nav.start': 'Conoce a I.R.I.S.',
      'manual.nav.chat': 'Chat y ayuda',
      'manual.nav.control': 'Voz y cámara',
      'manual.nav.files': 'Archivos y agentes',
      'manual.nav.editor': 'Workspace de desarrollo',
      'manual.nav.connections': 'Planes y conexiones',
      'manual.nav.safety': 'Seguridad y offline',
      'manual.start.h': 'Conoce a I.R.I.S.',
      'manual.start.p': 'I.R.I.S. es el asistente conversacional de GERAM: directo, con chispa y hecho para la ayuda del día a día. A.R.E.S. es el rol profesional de programación. Ambos viven ahora dentro de GERAM CORE OS y pueden usar el proveedor de IA que elijas en Ajustes.',
      'manual.start.callout.t': 'Habla con naturalidad',
      'manual.start.callout.d': 'Haz una pregunta o di “estado del sistema”. I.R.I.S. responde en el idioma que uses y recibe datos reales de CPU/RAM para las preguntas de hardware.'
    }
  };

  function normalize(lang) {
    return (lang === 'es' || lang === 'en') ? lang : null;
  }

  function getStored() {
    try { return normalize(root.localStorage.getItem(STORAGE_KEY)); } catch (e) { return null; }
  }

  function setStored(lang) {
    try { root.localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* private mode */ }
  }

  function t(key) {
    var table = DICT[current] || DICT[DEFAULT];
    if (table && Object.prototype.hasOwnProperty.call(table, key)) { return table[key]; }
    var base = DICT[DEFAULT];
    return (base && base[key] !== undefined) ? base[key] : key;
  }

  function applyAttr(scope, attr, setter) {
    var nodes = scope.querySelectorAll('[' + attr + ']');
    Array.prototype.forEach.call(nodes, function (node) {
      setter(node, t(node.getAttribute(attr)));
    });
  }

  function apply(scopeNode) {
    var scope = scopeNode || root.document;
    applyAttr(scope, 'data-i18n', function (n, v) { n.textContent = v; });
    applyAttr(scope, 'data-i18n-html', function (n, v) { n.innerHTML = v; });
    applyAttr(scope, 'data-i18n-title', function (n, v) { n.setAttribute('title', v); });
    applyAttr(scope, 'data-i18n-ph', function (n, v) { n.setAttribute('placeholder', v); });
    applyAttr(scope, 'data-i18n-aria', function (n, v) { n.setAttribute('aria-label', v); });
  }

  // Sincroniza la elección con el perfil del usuario para que el ASISTENTE
  // responda en el mismo idioma (best-effort; si falla, la UI ya quedó bien).
  function syncServer(lang) {
    if (!root.fetch) { return; }
    root.fetch('/api/config', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) { throw new Error('config'); } return r.json(); })
      .then(function (config) {
        if (!config.user_profile) { config.user_profile = {}; }
        if (config.user_profile.language === lang) { return null; }
        config.user_profile.language = lang;
        return root.fetch('/api/config', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config)
        });
      })
      .catch(function () { /* la UI ya está en el idioma elegido */ });
  }

  function setLanguage(lang, options) {
    var norm = normalize(lang) || DEFAULT;
    current = norm;
    setStored(norm);
    root.document.documentElement.setAttribute('lang', norm);
    apply(root.document);
    if (!options || options.sync !== false) { syncServer(norm); }
  }

  function hasChoice() { return getStored() !== null; }

  function init() {
    var stored = getStored();
    current = stored || DEFAULT;
    root.document.documentElement.setAttribute('lang', current);
    apply(root.document);
  }

  root.GeramI18n = {
    t: t,
    apply: apply,
    setLanguage: setLanguage,
    hasChoice: hasChoice,
    current: function () { return current; }
  };

  if (root.document.readyState === 'loading') {
    root.document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
