'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { createBackendManager, resolveLinuxPython, safeDistro } = require('../backend-manager');

test('WSL distro names are bounded and never become shell input', () => {
  assert.equal(safeDistro('Ubuntu-24.04'), 'Ubuntu-24.04');
  for (const value of ['../bad', 'Ubuntu;calc', 'x'.repeat(81)]) {
    assert.throws(() => safeDistro(value));
  }
});

test('development does not own the existing backend unless explicitly enabled', () => {
  const calls = [];
  const manager = createBackendManager({
    platform: 'linux', isPackaged: false, resourcesPath: '/opt/geram/resources',
    userData: '/tmp/geram-test-user', environment: {},
    spawn: (...args) => { calls.push(args); return {}; },
  });
  assert.equal(manager.start(8000), null);
  assert.equal(calls.length, 0);
});

test('packaged Linux starts only the fixed bootstrap profile', () => {
  const calls = [];
  const child = {};
  const manager = createBackendManager({
    platform: 'linux', isPackaged: true, resourcesPath: '/opt/geram/resources',
    userData: '/tmp/geram-test-user', environment: {},
    spawn: (...args) => { calls.push(args); return child; },
    spawnSync: (...args) => { calls.push(args); return { status: 0 }; },
  });
  assert.equal(manager.start(8000), child);
  assert.equal(calls[0][0], '/usr/bin/python3');
  assert.equal(calls[0][1].includes('--launch'), true);
  assert.equal(calls[0][2].shell, undefined);
  manager.stop();
  assert.equal(calls[1][0], '/usr/bin/python3');
  assert.equal(calls[1][1].includes('--stop'), true);
});

test('Linux resolves python3 outside /usr/bin instead of failing silently', () => {
  assert.equal(resolveLinuxPython(() => true), '/usr/bin/python3');
  assert.equal(
    resolveLinuxPython((candidate) => candidate === '/usr/local/bin/python3'),
    '/usr/local/bin/python3',
  );
  assert.equal(resolveLinuxPython(() => false), 'python3');
});

test('an asynchronous spawn failure surfaces instead of hanging the health poll', () => {
  const handlers = {};
  const failures = [];
  const manager = createBackendManager({
    platform: 'linux', isPackaged: true, resourcesPath: '/opt/geram/resources',
    userData: '/tmp/geram-test-user', environment: {},
    existsSync: () => true,
    onError: (error) => failures.push(error),
    spawn: () => ({ on: (event, handler) => { handlers[event] = handler; } }),
  });
  manager.start(8000);
  assert.equal(typeof handlers.error, 'function');
  handlers.error(Object.assign(new Error('spawn python3 ENOENT'), { code: 'ENOENT' }));
  assert.equal(failures.length, 1);
  assert.equal(failures[0].code, 'ENOENT');
});

test('packaged Windows converts paths and invokes a fixed WSL2 command', () => {
  const calls = [];
  const manager = createBackendManager({
    platform: 'win32', isPackaged: true, resourcesPath: 'C:\\Program Files\\GERAM\\resources',
    userData: 'C:\\Users\\Test\\AppData\\Local\\GERAM', environment: { GERAM_WSL_DISTRO: 'Ubuntu-24.04' },
    spawn: (...args) => { calls.push(['async', ...args]); return {}; },
    spawnSync: (command, args) => {
      calls.push(['sync', command, args]);
      const value = args[args.length - 1].endsWith('bootstrap_backend.py')
        ? '/mnt/c/Program Files/GERAM/resources/backend-payload/bootstrap_backend.py\n'
        : '/mnt/c/Program Files/GERAM/resources/backend-payload\n';
      return { status: 0, stdout: value };
    },
  });
  manager.start(8000);
  const start = calls.find((entry) => entry[0] === 'async');
  assert.equal(start[1], 'wsl.exe');
  assert.equal(start[2].includes('python3'), true);
  assert.equal(start[2].includes('--launch'), true);
  assert.equal(start[3].shell, undefined);
});
