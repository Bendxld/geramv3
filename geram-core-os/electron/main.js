// ============================================================
// GERAM CORE OS · electron/main.js
//
// Contenedor Electron para el HUD (static/ del backend FastAPI).
// No sirve ni transforma el HTML/CSS/JS — solo abre una ventana
// nativa que carga http://127.0.0.1:8000/ una vez que el backend
// (uvicorn) confirma estar arriba. El HUD en sí no se toca.
// ============================================================

const { app, BrowserWindow, Menu, dialog, globalShortcut, session } = require('electron');
const http = require('http');
const { createBackendManager } = require('./backend-manager');
const { createLoopbackPolicy, normalizePort } = require('./network-policy');
const {
  applyChromiumNetworkReductionSwitches,
  configureSession,
  createWindowOptions,
  registerWebContentsPolicy,
  secureWebContents,
} = require('./security-controls');

const HUD_PORT = normalizePort(process.env.GERAM_ELECTRON_PORT || 8000);
const HUD_URL = `http://127.0.0.1:${HUD_PORT}/`;
const HEALTH_URL = `http://127.0.0.1:${HUD_PORT}/health`;
const HEALTH_TIMEOUT_MS = app.isPackaged ? 180000 : 20000;
const HEALTH_POLL_INTERVAL_MS = 500;
const NETWORK_POLICY = createLoopbackPolicy({
  port: HUD_PORT,
  allowLocalhost: true,
  allowIpv6: true,
});

let ventanaPrincipal = null;
let backendManager = null;

app.setName('GERAM CORE OS');
app.commandLine.appendSwitch('class', 'geram-core-os');
const tieneBloqueoDeInstancia = app.requestSingleInstanceLock();

if (!tieneBloqueoDeInstancia) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!ventanaPrincipal) return;
    if (ventanaPrincipal.isMinimized()) ventanaPrincipal.restore();
    ventanaPrincipal.show();
    ventanaPrincipal.focus();
  });
}

function reportarBloqueo(mensajeSanitizado) {
  console.warn(mensajeSanitizado);
}

// Estos switches reducen actividad autónoma evitable del runtime. La barrera de
// seguridad real está además en la sesión y en cada webContents; no se confía sólo
// en argumentos de Chromium.
applyChromiumNetworkReductionSwitches(app);
registerWebContentsPolicy(app, NETWORK_POLICY, reportarBloqueo);

// Poll a /health hasta que responda 200 o se agote el timeout — Electron
// suele arrancar más rápido que uvicorn, así que no hay que asumir que
// el backend ya está listo cuando esta app arranca.
function esperarBackend(timeoutMs) {
  return new Promise((resolve, reject) => {
    const inicio = Date.now();

    function intentar() {
      let terminado = false;
      const req = http.get(HEALTH_URL, { timeout: 1000 }, (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => {
          body += chunk;
          if (body.length > 1024) fallarIntento();
        });
        res.on('end', () => {
          if (terminado) return;
          try {
            const payload = JSON.parse(body);
            if (res.statusCode === 200 && payload && payload.status === 'ok') {
              terminado = true;
              resolve();
              return;
            }
          } catch (_error) {
            // A 200 from another local service is not GERAM CORE OS health.
          }
          fallarIntento();
        });
      });
      function fallarIntento() {
        if (terminado) return;
        terminado = true;
        req.destroy();
        reintentar();
      }
      req.on('timeout', fallarIntento);
      req.on('error', fallarIntento);
    }

    function reintentar() {
      if (Date.now() - inicio >= timeoutMs) {
        reject(new Error('/health no respondió 200 tras ' + timeoutMs + 'ms'));
        return;
      }
      setTimeout(intentar, HEALTH_POLL_INTERVAL_MS);
    }

    intentar();
  });
}

function crearVentana(appSession) {
  ventanaPrincipal = new BrowserWindow(createWindowOptions(appSession, true));
  secureWebContents(ventanaPrincipal.webContents, NETWORK_POLICY, reportarBloqueo);

  if (!NETWORK_POLICY.isAllowed(HUD_URL)) {
    throw new Error('La URL local del HUD no cumple la política Electron.');
  }
  ventanaPrincipal.loadURL(HUD_URL).catch(() => {
    console.error('ERROR: no se pudo cargar el HUD local.');
    app.quit();
  });

  ventanaPrincipal.on('closed', () => {
    ventanaPrincipal = null;
  });
}

// El backend puede fallar de dos formas: síncrona (WSL2 sin preparar) o
// asíncrona (spawn con ENOENT). Ambas terminan aquí, y sólo una vez.
let arranqueYaFallo = false;
function fallarArranqueDelBackend() {
  if (arranqueYaFallo) return;
  arranqueYaFallo = true;
  dialog.showErrorBox(
    'GERAM CORE OS could not start',
    process.platform === 'win32'
      ? 'WSL2 is not prepared. Run GERAM Windows Setup from the installation resources and try again.'
      : 'The packaged backend could not start. Verify that Python 3 is installed.',
  );
  app.quit();
}

if (tieneBloqueoDeInstancia) app.whenReady().then(async () => {
  // Sin menú de aplicación — nada de barra "File/Edit/View" nativa.
  Menu.setApplicationMenu(null);

  backendManager = createBackendManager({
    platform: process.platform,
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    userData: app.getPath('userData'),
    environment: process.env,
    onError: () => fallarArranqueDelBackend(),
  });
  try {
    backendManager.start(HUD_PORT);
  } catch (_error) {
    fallarArranqueDelBackend();
    return;
  }

  // Sin prefijo persist: esta partición existe sólo en memoria. Su política se
  // instala y su proxy se fija antes de que BrowserWindow cargue un solo recurso.
  const appSession = session.fromPartition('geram-local');
  try {
    await configureSession(appSession, NETWORK_POLICY, reportarBloqueo);
  } catch (_error) {
    console.error('ERROR: no se pudo aplicar la política de red local de Electron.');
    app.quit();
    return;
  }

  try {
    console.log('Esperando a que el backend (uvicorn) responda /health...');
    await esperarBackend(HEALTH_TIMEOUT_MS);
    console.log('Backend listo, abriendo ventana del HUD.');
  } catch (err) {
    console.error('ERROR: ' + err.message);
    console.error(`¿Está corriendo GERAM CORE OS en el puerto local ${HUD_PORT}? Aborta el arranque.`);
    app.quit();
    return;
  }

  crearVentana(appSession);

  // Salida explícita para desarrollo/kiosk: Ctrl+Q (Cmd+Q en mac).
  // En kiosk real (frame:false) no hay ninguna otra forma obvia de
  // cerrar la ventana desde el teclado, así que este atajo es
  // intencional y necesario.
  globalShortcut.register('CommandOrControl+Q', () => {
    app.quit();
  });
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (backendManager) backendManager.stop();
});
