'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');
const { createLoopbackPolicy } = require('../network-policy');
const {
  CHROMIUM_NETWORK_REDUCTION_SWITCHES,
  applyChromiumNetworkReductionSwitches,
  configureSession,
  createContentSecurityPolicy,
  createWindowOptions,
  formatBlockedAttempt,
  registerWebContentsPolicy,
  secureWebContents,
} = require('../security-controls');

const policy = createLoopbackPolicy({ port: 8000 });

class FakeWebRequest {
  onBeforeRequest(_filter, listener) {
    this.beforeRequest = listener;
  }

  onBeforeRedirect(_filter, listener) {
    this.beforeRedirect = listener;
  }

  onHeadersReceived(_filter, listener) {
    this.headersReceived = listener;
  }
}

class FakeSession extends EventEmitter {
  constructor() {
    super();
    this.webRequest = new FakeWebRequest();
  }

  setPermissionCheckHandler(handler) {
    this.permissionCheckHandler = handler;
  }

  setPermissionRequestHandler(handler) {
    this.permissionRequestHandler = handler;
  }

  setDevicePermissionHandler(handler) {
    this.devicePermissionHandler = handler;
  }

  setDisplayMediaRequestHandler(handler) {
    this.displayMediaRequestHandler = handler;
  }

  setSpellCheckerEnabled(value) {
    this.spellCheckerEnabled = value;
  }

  setProxy(config) {
    this.proxyConfig = config;
    return Promise.resolve();
  }
}

class FakeWebContents extends EventEmitter {
  constructor(appSession) {
    super();
    this.session = appSession;
    this.stopped = false;
  }

  setWindowOpenHandler(handler) {
    this.windowOpenHandler = handler;
  }

  stop() {
    this.stopped = true;
  }
}

function requestDecision(appSession, url, resourceType = 'xhr') {
  return new Promise((resolve) => {
    appSession.webRequest.beforeRequest({ url, resourceType }, resolve);
  });
}

function preventableEvent(url) {
  return {
    url,
    prevented: false,
    preventDefault() {
      this.prevented = true;
    },
  };
}

test('la sesión usa proxy directo y desactiva el corrector remoto', async () => {
  const appSession = new FakeSession();
  await configureSession(appSession, policy);
  assert.deepEqual(appSession.proxyConfig, { mode: 'direct' });
  assert.equal(appSession.spellCheckerEnabled, false);
});

test('la página local y el backend loopback continúan accesibles', async () => {
  const appSession = new FakeSession();
  await configureSession(appSession, policy);
  assert.deepEqual(
    await requestDecision(appSession, 'http://127.0.0.1:8000/'),
    { cancel: false },
  );
  assert.deepEqual(
    await requestDecision(appSession, 'http://127.0.0.1:8000/workspace/tree'),
    { cancel: false },
  );
  assert.deepEqual(
    await requestDecision(appSession, 'ws://127.0.0.1:8000/ws/hud', 'webSocket'),
    { cancel: false },
  );
});

test('subrecursos externos se cancelan sin depender del tipo', async () => {
  const appSession = new FakeSession();
  await configureSession(appSession, policy);
  for (const resourceType of ['image', 'font', 'script', 'other', 'media']) {
    assert.deepEqual(
      await requestDecision(appSession, 'https://example.invalid/resource', resourceType),
      { cancel: true },
    );
  }
});

test('fetch, worker y WebSocket externos se cancelan', async () => {
  const appSession = new FakeSession();
  await configureSession(appSession, policy);
  for (const [url, resourceType] of [
    ['https://example.invalid/api', 'xhr'],
    ['https://example.invalid/worker.js', 'script'],
    ['wss://example.invalid/socket', 'webSocket'],
  ]) {
    assert.deepEqual(await requestDecision(appSession, url, resourceType), {
      cancel: true,
    });
  }
});

test('una redirección externa se detecta y el siguiente salto se cancela', async () => {
  const appSession = new FakeSession();
  const blocked = [];
  await configureSession(appSession, policy, (message) => blocked.push(message));
  appSession.webRequest.beforeRedirect({
    redirectURL: 'https://example.invalid/next?token=secret',
    resourceType: 'mainFrame',
  });
  assert.equal(blocked.length, 1);
  assert.deepEqual(
    await requestDecision(appSession, 'https://example.invalid/next?token=secret', 'mainFrame'),
    { cancel: true },
  );
});

test('la CSP permite únicamente workers locales sin recursos remotos', () => {
  const csp = createContentSecurityPolicy(8000);
  assert.match(csp, /worker-src 'self'/);
  assert.doesNotMatch(csp, /worker-src[^;]*(?:https?:|blob:|\*)/);
  assert.doesNotMatch(csp, /(?:^|\s)'unsafe-eval'(?:\s|;|$)/);
  assert.match(csp, /'wasm-unsafe-eval'/);
  assert.match(csp, /script-src 'self'/);
  assert.match(csp, /font-src 'self'/);
  assert.equal(csp.includes('ws://[::1]'), false);
  assert.equal(csp.includes('https://'), false);
  assert.equal(csp.includes('wss://'), false);
});

test('la CSP se añade sólo a la respuesta principal local', async () => {
  const appSession = new FakeSession();
  await configureSession(appSession, policy);
  const response = await new Promise((resolve) => {
    appSession.webRequest.headersReceived({
      url: 'http://127.0.0.1:8000/',
      resourceType: 'mainFrame',
      responseHeaders: { 'X-Test': ['ok'] },
    }, resolve);
  });
  assert.equal(response.responseHeaders['X-Test'][0], 'ok');
  assert.match(response.responseHeaders['Content-Security-Policy'][0], /worker-src 'self'/);
});

test('sólo micrófono y cámara locales se permiten; lo demás se deniega', async () => {
  const appSession = new FakeSession();
  await configureSession(appSession, policy);
  for (const permission of [
    'geolocation', 'midi', 'notifications', 'openExternal',
    'serial', 'usb', 'clipboard-read', 'fileSystem',
  ]) {
    assert.equal(appSession.permissionCheckHandler(null, permission, '', {}), false);
    const granted = await new Promise((resolve) => {
      appSession.permissionRequestHandler(null, permission, resolve, {});
    });
    assert.equal(granted, false);
  }
  const localMedia = {
    requestingUrl: 'http://127.0.0.1:8000/',
    mediaTypes: ['audio', 'video'],
  };
  assert.equal(
    appSession.permissionCheckHandler(null, 'media', localMedia.requestingUrl, localMedia),
    true,
  );
  assert.equal(await new Promise((resolve) => {
    appSession.permissionRequestHandler(null, 'media', resolve, localMedia);
  }), true);
  for (const details of [
    { requestingUrl: 'https://example.invalid/', mediaTypes: ['audio'] },
    { requestingUrl: 'http://127.0.0.1:8000/', mediaTypes: ['display-capture'] },
    { requestingUrl: 'http://127.0.0.1:8000/', mediaTypes: [] },
  ]) {
    assert.equal(await new Promise((resolve) => {
      appSession.permissionRequestHandler(null, 'media', resolve, details);
    }), false);
  }
  assert.equal(appSession.devicePermissionHandler({ deviceType: 'usb' }), false);
  const streams = await new Promise((resolve) => {
    appSession.displayMediaRequestHandler({}, resolve);
  });
  assert.deepEqual(streams, {});
});

test('todas las descargas se cancelan', async () => {
  const appSession = new FakeSession();
  await configureSession(appSession, policy);
  const event = preventableEvent('');
  appSession.emit('will-download', event, {
    getURL: () => 'https://example.invalid/file?token=secret',
  });
  assert.equal(event.prevented, true);
});

test('navegación principal y de frames externa se bloquea', () => {
  const contents = new FakeWebContents(new FakeSession());
  secureWebContents(contents, policy);
  for (const eventName of ['will-navigate', 'will-frame-navigate']) {
    const event = preventableEvent('https://example.invalid/');
    contents.emit(eventName, event);
    assert.equal(event.prevented, true);
  }
  const localEvent = preventableEvent('http://127.0.0.1:8000/workspace');
  contents.emit('will-navigate', localEvent);
  assert.equal(localEvent.prevented, false);
});

test('la redirección de navegación externa se bloquea', () => {
  const contents = new FakeWebContents(new FakeSession());
  secureWebContents(contents, policy);
  const event = preventableEvent('https://example.invalid/redirected');
  contents.emit('will-redirect', event);
  assert.equal(event.prevented, true);
});

test('window.open y webviews se deniegan', () => {
  const contents = new FakeWebContents(new FakeSession());
  secureWebContents(contents, policy);
  assert.deepEqual(
    contents.windowOpenHandler({ url: 'https://example.invalid/' }),
    { action: 'deny' },
  );
  assert.deepEqual(
    contents.windowOpenHandler({ url: 'http://127.0.0.1:8000/' }),
    { action: 'deny' },
  );
  const event = preventableEvent('');
  contents.emit('will-attach-webview', event);
  assert.equal(event.prevented, true);
});

test('todo webContents adicional recibe la misma política de sesión', async () => {
  const app = new EventEmitter();
  const appSession = new FakeSession();
  const contents = new FakeWebContents(appSession);
  registerWebContentsPolicy(app, policy);
  app.emit('web-contents-created', {}, contents);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(typeof appSession.webRequest.beforeRequest, 'function');
  assert.equal(typeof contents.windowOpenHandler, 'function');
  assert.deepEqual(
    await requestDecision(appSession, 'https://example.invalid/', 'mainFrame'),
    { cancel: true },
  );
});

test('los modos normal y kiosk conservan idénticas preferencias seguras', () => {
  const appSession = new FakeSession();
  const normal = createWindowOptions(appSession, false);
  const kiosk = createWindowOptions(appSession, true);
  assert.deepEqual(normal.webPreferences, kiosk.webPreferences);
  assert.equal(normal.kiosk, false);
  assert.equal(kiosk.kiosk, true);
});

test('BrowserWindow no relaja aislamiento, sandbox ni webSecurity', () => {
  const options = createWindowOptions(new FakeSession(), true);
  assert.equal(options.webPreferences.nodeIntegration, false);
  assert.equal(options.webPreferences.nodeIntegrationInSubFrames, false);
  assert.equal(options.webPreferences.nodeIntegrationInWorker, false);
  assert.equal(options.webPreferences.contextIsolation, true);
  assert.equal(options.webPreferences.sandbox, true);
  assert.equal(options.webPreferences.webSecurity, true);
  assert.equal(options.webPreferences.allowRunningInsecureContent, false);
  assert.equal(options.webPreferences.webviewTag, false);
});

test('los avisos bloqueados no exponen URL, token, query ni fragment', () => {
  const secret = 'valor-super-secreto';
  const message = formatBlockedAttempt(
    'request',
    'xhr',
    `https://usuario:${secret}@example.invalid/path?token=${secret}#${secret}`,
    policy,
  );
  assert.equal(message.includes(secret), false);
  assert.equal(message.includes('example.invalid'), false);
  assert.equal(message.includes('?'), false);
  assert.equal(message.includes('#'), false);
});

test('los switches de reducción cubren runtime, DNS y componentes', () => {
  const app = {
    commandLine: {
      calls: [],
      appendSwitch(...args) {
        this.calls.push(args);
      },
    },
  };
  applyChromiumNetworkReductionSwitches(app);
  assert.deepEqual(app.commandLine.calls, CHROMIUM_NETWORK_REDUCTION_SWITCHES);
  const names = new Set(app.commandLine.calls.map(([name]) => name));
  for (const name of [
    'disable-background-networking',
    'disable-component-update',
    'disable-domain-reliability',
    'dns-prefetch-disable',
    'host-resolver-rules',
  ]) {
    assert.equal(names.has(name), true);
  }
  const resolverRules = app.commandLine.calls.find(
    ([name]) => name === 'host-resolver-rules',
  )[1];
  assert.match(resolverRules, /EXCLUDE 127\.0\.0\.1/);
  assert.match(resolverRules, /EXCLUDE localhost/);
  assert.match(resolverRules, /EXCLUDE \[::1\]/);
});
