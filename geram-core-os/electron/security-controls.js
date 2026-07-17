'use strict';

const configuredSessions = new WeakMap();
const configuredWebContents = new WeakSet();

const CHROMIUM_NETWORK_REDUCTION_SWITCHES = Object.freeze([
  ['disable-background-networking'],
  ['disable-breakpad'],
  ['disable-client-side-phishing-detection'],
  ['disable-component-update'],
  ['disable-default-apps'],
  ['disable-domain-reliability'],
  ['disable-sync'],
  ['disable-translate'],
  ['dns-prefetch-disable'],
  ['metrics-recording-only'],
  ['no-first-run'],
  ['no-pings'],
  [
    'disable-features',
    'AutofillServerCommunication,CertificateTransparencyComponentUpdater,MediaRouter,OptimizationHints',
  ],
  [
    'host-resolver-rules',
    'MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost, EXCLUDE [::1]',
  ],
]);

function createContentSecurityPolicy(port) {
  return [
    "default-src 'self'",
    "base-uri 'none'",
    `connect-src 'self' ws://127.0.0.1:${port} ws://localhost:${port}`,
    "font-src 'self'",
    "form-action 'none'",
    "frame-ancestors 'none'",
    "frame-src 'self'",
    "img-src 'self' data:",
    "media-src 'self'",
    "object-src 'none'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "worker-src 'self'",
  ].join('; ');
}

function formatBlockedAttempt(source, resourceType, rawDestination, policy) {
  const summary = policy.summarize(rawDestination);
  const safeSource = /^[a-z-]+$/.test(source) ? source : 'unknown';
  const safeType = /^[A-Za-z-]+$/.test(resourceType || '')
    ? resourceType
    : 'unknown';
  return (
    `[Electron security] blocked source=${safeSource} type=${safeType} ` +
    `protocol=${summary.protocol} destination=${summary.destination}`
  );
}

function appendResponseHeader(responseHeaders, name, value) {
  const headers = { ...(responseHeaders || {}) };
  const existingName = Object.keys(headers).find(
    (headerName) => headerName.toLowerCase() === name.toLowerCase(),
  );

  if (existingName) {
    headers[existingName] = [...headers[existingName], value];
  } else {
    headers[name] = [value];
  }
  return headers;
}

function configureSession(appSession, policy, onBlocked = () => {}) {
  const existingConfiguration = configuredSessions.get(appSession);
  if (existingConfiguration) {
    return existingConfiguration;
  }

  const filter = { urls: ['<all_urls>'] };
  const csp = createContentSecurityPolicy(policy.port);

  appSession.webRequest.onBeforeRequest(filter, (details, callback) => {
    const allowed = policy.isAllowed(details.url);
    if (!allowed) {
      onBlocked(formatBlockedAttempt(
        'request',
        details.resourceType,
        details.url,
        policy,
      ));
    }
    callback({ cancel: !allowed });
  });

  // Electron no permite cancelar desde onBeforeRedirect. La navegación principal
  // se detiene en will-redirect y el siguiente salto de cualquier recurso vuelve a
  // pasar por onBeforeRequest antes de abrirse.
  appSession.webRequest.onBeforeRedirect(filter, (details) => {
    if (!policy.isAllowed(details.redirectURL)) {
      onBlocked(formatBlockedAttempt(
        'redirect',
        details.resourceType,
        details.redirectURL,
        policy,
      ));
    }
  });

  appSession.webRequest.onHeadersReceived(filter, (details, callback) => {
    if (details.resourceType !== 'mainFrame' || !policy.isAllowed(details.url)) {
      callback({ responseHeaders: details.responseHeaders });
      return;
    }

    callback({
      responseHeaders: appendResponseHeader(
        details.responseHeaders,
        'Content-Security-Policy',
        csp,
      ),
    });
  });

  appSession.setPermissionCheckHandler(() => false);
  appSession.setPermissionRequestHandler((_contents, _permission, callback) => {
    callback(false);
  });
  appSession.setDevicePermissionHandler(() => false);
  appSession.setDisplayMediaRequestHandler((_request, callback) => {
    callback({});
  });
  appSession.setSpellCheckerEnabled(false);

  appSession.on('will-download', (event, item) => {
    const downloadUrl = item && typeof item.getURL === 'function'
      ? item.getURL()
      : '';
    onBlocked(formatBlockedAttempt('download', 'download', downloadUrl, policy));
    event.preventDefault();
  });

  // Esta sesión es propia y en memoria. El modo directo evita heredar HTTP_PROXY,
  // HTTPS_PROXY o PAC del entorno sin modificar la configuración global del usuario.
  const configuration = Promise.resolve(appSession.setProxy({ mode: 'direct' }))
    .catch(() => {
      throw new Error('No se pudo fijar la sesión Electron en modo de proxy directo.');
    });
  configuredSessions.set(appSession, configuration);
  return configuration;
}

function eventDestination(details, legacyUrl) {
  if (details && typeof details.url === 'string') {
    return details.url;
  }
  return legacyUrl;
}

function secureWebContents(contents, policy, onBlocked = () => {}) {
  if (configuredWebContents.has(contents)) {
    return;
  }
  configuredWebContents.add(contents);

  function blockUnsafeNavigation(source, details, legacyUrl) {
    const destination = eventDestination(details, legacyUrl);
    if (!policy.isAllowed(destination)) {
      onBlocked(formatBlockedAttempt(source, 'navigation', destination, policy));
      details.preventDefault();
    }
  }

  contents.on('will-navigate', (details, legacyUrl) => {
    blockUnsafeNavigation('navigation', details, legacyUrl);
  });
  contents.on('will-frame-navigate', (details) => {
    blockUnsafeNavigation('frame-navigation', details);
  });
  contents.on('will-redirect', (details, legacyUrl) => {
    blockUnsafeNavigation('redirect', details, legacyUrl);
  });
  contents.on('will-attach-webview', (event) => {
    onBlocked(formatBlockedAttempt('webview', 'webview', '', policy));
    event.preventDefault();
  });

  // El HUD no necesita ventanas secundarias. Denegarlas todas evita que una ruta
  // local se use como trampolín hacia una navegación posterior externa.
  contents.setWindowOpenHandler((details) => {
    onBlocked(formatBlockedAttempt('window-open', 'window', details.url, policy));
    return { action: 'deny' };
  });
}

function registerWebContentsPolicy(app, policy, onBlocked = () => {}) {
  app.on('web-contents-created', (_event, contents) => {
    configureSession(contents.session, policy, onBlocked).catch(() => {
      onBlocked('[Electron security] session configuration failed');
      contents.stop();
    });
    secureWebContents(contents, policy, onBlocked);
  });
}

function createWindowOptions(appSession, kiosk = true) {
  return {
    kiosk,
    fullscreen: kiosk,
    frame: !kiosk,
    autoHideMenuBar: true,
    webPreferences: {
      session: appSession,
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInSubFrames: false,
      nodeIntegrationInWorker: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      spellcheck: false,
      enableWebSQL: false,
      navigateOnDragDrop: false,
    },
  };
}

function applyChromiumNetworkReductionSwitches(app) {
  for (const [name, value] of CHROMIUM_NETWORK_REDUCTION_SWITCHES) {
    if (value === undefined) {
      app.commandLine.appendSwitch(name);
    } else {
      app.commandLine.appendSwitch(name, value);
    }
  }
}

module.exports = {
  CHROMIUM_NETWORK_REDUCTION_SWITCHES,
  applyChromiumNetworkReductionSwitches,
  configureSession,
  createContentSecurityPolicy,
  createWindowOptions,
  formatBlockedAttempt,
  registerWebContentsPolicy,
  secureWebContents,
};
