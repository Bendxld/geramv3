'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const ROOT = path.resolve(__dirname, '..', '..');
const mainSource = fs.readFileSync(path.join(ROOT, 'electron/main.js'), 'utf8');
const startSource = fs.readFileSync(path.join(ROOT, 'iniciar_app.sh'), 'utf8');
const stopSource = fs.readFileSync(path.join(ROOT, 'salir_app.sh'), 'utf8');
const desktopSource = fs.readFileSync(path.join(ROOT, 'linux/geram-core-os.desktop'), 'utf8');

test('Electron usa lock de instancia única y enfoca la ventana existente', () => {
  assert.match(mainSource, /requestSingleInstanceLock\(\)/);
  assert.match(mainSource, /app\.on\('second-instance'/);
  assert.match(mainSource, /ventanaPrincipal\.focus\(\)/);
});

test('Electron exige el contrato JSON real de health', () => {
  assert.match(mainSource, /JSON\.parse\(body\)/);
  assert.match(mainSource, /payload\.status === 'ok'/);
  assert.match(mainSource, /body\.length > 1024/);
});

test('scripts de escritorio delegan sin nohup, pkill ni matching débil', () => {
  for (const source of [startSource, stopSource]) {
    assert.match(source, /desktop_launcher\.py/);
    assert.doesNotMatch(source, /nohup|pkill|pgrep|server\.py/);
  }
});

test('desktop entry es local, gráfico y usa el icono versionado', () => {
  assert.match(desktopSource, /^Name=GERAM CORE OS$/m);
  assert.match(desktopSource, /^Terminal=false$/m);
  assert.match(desktopSource, /^StartupWMClass=geram-core-os$/m);
  assert.match(desktopSource, /\/geram-core-os\/iniciar_app\.sh$/m);
  assert.match(desktopSource, /\/geram-core-os\/static\/favicon\.svg$/m);
});
