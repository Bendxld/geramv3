'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');

// Rutas fijas primero (lo habitual en Debian/Ubuntu, el objetivo de release) y
// PATH como último recurso, para no romper en distros que no ponen python3 en
// /usr/bin. La lista es cerrada: nada de aquí viene de entrada del usuario.
const LINUX_PYTHON_CANDIDATES = ['/usr/bin/python3', '/usr/local/bin/python3'];

function resolveLinuxPython(exists) {
  for (const candidate of LINUX_PYTHON_CANDIDATES) {
    if (exists(candidate)) return candidate;
  }
  return 'python3';
}

function safeDistro(value) {
  const selected = String(value || 'Ubuntu-24.04').trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$/.test(selected)) {
    throw new Error('GERAM_WSL_DISTRO is invalid.');
  }
  return selected;
}

function createBackendManager(options) {
  const run = options.spawn || spawn;
  const runSync = options.spawnSync || spawnSync;
  const platform = options.platform;
  const exists = options.existsSync || fs.existsSync;
  const onError = options.onError || (() => {});
  const payload = path.join(options.resourcesPath, 'backend-payload');
  const bootstrap = path.join(payload, 'bootstrap_backend.py');
  const ownerToken = crypto.randomBytes(16).toString('hex');
  const dataDir = options.userData;
  let child = null;
  let windowsPaths = null;

  function convertWindowsPaths() {
    if (windowsPaths) return windowsPaths;
    const distro = safeDistro(options.environment.GERAM_WSL_DISTRO);
    function convert(value) {
      const result = runSync('wsl.exe', ['-d', distro, '--', 'wslpath', '-a', '-u', value], {
        encoding: 'utf8', windowsHide: true,
      });
      if (result.status !== 0 || !String(result.stdout || '').trim().startsWith('/')) {
        throw new Error('WSL2 is not ready. Run the bundled GERAM Windows setup.');
      }
      return String(result.stdout).trim();
    }
    windowsPaths = { distro, payload: convert(payload), bootstrap: convert(bootstrap) };
    return windowsPaths;
  }

  function start(port) {
    if (!options.isPackaged && options.environment.GERAM_MANAGE_BACKEND !== '1') return null;
    if (platform === 'win32') {
      const converted = convertWindowsPaths();
      child = run('wsl.exe', [
        '-d', converted.distro, '--', 'python3', converted.bootstrap,
        '--payload', converted.payload,
        '--data-dir', '~/.local/share/geram-core-os',
        '--port', String(port), '--owner-token', ownerToken, '--launch',
      ], { stdio: 'ignore', windowsHide: true });
    } else {
      child = run(resolveLinuxPython(exists), [
        bootstrap, '--payload', payload, '--data-dir', dataDir,
        '--port', String(port), '--owner-token', ownerToken, '--launch',
      ], { stdio: 'ignore' });
    }
    // spawn falla de forma asíncrona (ENOENT y compañía): sin esto el arranque
    // se cuelga hasta que expira el health poll, sin decirle nada al usuario.
    if (child && typeof child.on === 'function') {
      child.on('error', (error) => {
        child = null;
        onError(error);
      });
    }
    return child;
  }

  function stop() {
    if (!child) return;
    if (platform === 'win32') {
      const converted = convertWindowsPaths();
      runSync('wsl.exe', [
        '-d', converted.distro, '--', 'python3', converted.bootstrap,
        '--data-dir', '~/.local/share/geram-core-os',
        '--owner-token', ownerToken, '--stop',
      ], { stdio: 'ignore', windowsHide: true, timeout: 7000 });
    } else {
      runSync(resolveLinuxPython(exists), [
        bootstrap, '--data-dir', dataDir, '--owner-token', ownerToken, '--stop',
      ], { stdio: 'ignore', timeout: 7000 });
    }
    child = null;
  }

  return { start, stop };
}

module.exports = { createBackendManager, resolveLinuxPython, safeDistro };
