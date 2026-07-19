'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

test('release configuration builds Linux and Windows installers with the offline backend payload', () => {
  const root = path.resolve(__dirname, '../..');
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'electron/package.json'), 'utf8'));
  assert.equal(pkg.devDependencies['electron-builder'], '26.15.3');
  assert.deepEqual(pkg.build.win.target, ['nsis']);
  assert.deepEqual(pkg.build.linux.target, ['AppImage', 'deb']);
  assert.equal(pkg.build.extraResources.some((item) => item.to === 'backend-payload'), true);
  assert.match(pkg.scripts['dist:windows'], /--win nsis/);
  assert.match(pkg.scripts['dist:linux'], /AppImage deb/);
});

test('Windows setup requires WSL2 and the same Bubblewrap boundary', () => {
  const root = path.resolve(__dirname, '../..');
  const setup = fs.readFileSync(path.join(root, 'windows/GERAM-Windows-Setup.ps1'), 'utf8');
  assert.match(setup, /wsl\.exe/);
  assert.match(setup, /bubblewrap/);
  assert.match(setup, /python3-venv/);
  assert.doesNotMatch(setup, /Invoke-Expression|Start-Process.+-Verb\s+RunAs/);
});
