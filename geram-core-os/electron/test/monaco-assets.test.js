'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const {
  stripTrailingSourceMapDirective,
} = require('../scripts/prepare-monaco-assets.js');

const ROOT = path.resolve(__dirname, '../..');
const ELECTRON_ROOT = path.join(ROOT, 'electron');
const VENDOR_ROOT = path.join(ROOT, 'static', 'vendor', 'monaco');
const VS_ROOT = path.join(VENDOR_ROOT, 'vs');
const SOURCE_VS_ROOT = path.join(
  ELECTRON_ROOT,
  'node_modules',
  'monaco-editor',
  'min',
  'vs'
);
const RECOVERED_ASSETS = [
  'language/typescript/tsWorker.js',
  'nls.messages.de.js',
  'nls.messages.es.js',
  'nls.messages.fr.js',
  'nls.messages.it.js',
  'nls.messages.ja.js',
  'nls.messages.ko.js',
  'nls.messages.ru.js',
  'nls.messages.zh-cn.js',
  'nls.messages.zh-tw.js'
];

function filesUnder(directory, relative = '') {
  return fs.readdirSync(path.join(directory, relative), { withFileTypes: true })
    .flatMap((entry) => {
      const child = path.join(relative, entry.name);
      return entry.isDirectory() ? filesUnder(directory, child) : [child];
    });
}

test('package y lock fijan exactamente monaco-editor 0.52.2 con integridad', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(ELECTRON_ROOT, 'package.json')));
  const lock = JSON.parse(fs.readFileSync(path.join(ELECTRON_ROOT, 'package-lock.json')));
  assert.equal(packageJson.devDependencies['monaco-editor'], '0.52.2');
  const locked = lock.packages['node_modules/monaco-editor'];
  assert.equal(locked.version, '0.52.2');
  assert.equal(locked.license, 'MIT');
  assert.match(locked.integrity, /^sha512-/);
});

test('manifiesto local coincide con versión, licencia y cantidad de assets', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(VENDOR_ROOT, 'manifest.json')));
  assert.deepEqual(
    {
      package: manifest.package,
      version: manifest.version,
      license: manifest.license,
      runtime: manifest.runtime,
      source_maps: manifest.source_maps
    },
    {
      package: 'monaco-editor',
      version: '0.52.2',
      license: 'MIT',
      runtime: 'min/vs',
      source_maps: false
    }
  );
  assert.equal(filesUnder(VS_ROOT).length, manifest.asset_count);
});

test('runtime incluye editor, estilos y workers locales requeridos', () => {
  for (const relative of [
    'loader.js',
    'editor/editor.main.js',
    'editor/editor.main.css',
    'base/worker/workerMain.js',
    'language/json/jsonWorker.js',
    'language/css/cssWorker.js',
    'language/html/htmlWorker.js',
    'language/typescript/tsWorker.js'
  ]) {
    assert.equal(fs.statSync(path.join(VS_ROOT, relative)).isFile(), true, relative);
  }
});

test('activos vendorizados no contienen mapas ni directivas finales activas', () => {
  const files = filesUnder(VS_ROOT);
  assert.equal(files.some((file) => file.endsWith('.map')), false);
  for (const file of files.filter((name) => /\.(?:js|css)$/.test(name))) {
    const source = fs.readFileSync(path.join(VS_ROOT, file), 'utf8');
    assert.equal(stripTrailingSourceMapDirective(source), source, file);
  }
});

test('runtime publicado coincide con el paquete salvo directivas finales permitidas', () => {
  const sourceFiles = filesUnder(SOURCE_VS_ROOT).sort();
  const publishedFiles = filesUnder(VS_ROOT).sort();
  assert.deepEqual(publishedFiles, sourceFiles);
  for (const file of sourceFiles) {
    const source = fs.readFileSync(path.join(SOURCE_VS_ROOT, file));
    const expected = /\.(?:js|css)$/.test(file)
      ? Buffer.from(stripTrailingSourceMapDirective(source.toString('utf8')), 'utf8')
      : source;
    assert.deepEqual(fs.readFileSync(path.join(VS_ROOT, file)), expected, file);
  }
});

test('los diez activos recuperados conservan texto legítimo sourceMappingURL', () => {
  for (const file of RECOVERED_ASSETS) {
    const source = fs.readFileSync(path.join(SOURCE_VS_ROOT, file), 'utf8');
    const published = fs.readFileSync(path.join(VS_ROOT, file), 'utf8');
    assert.match(source, /sourceMappingURL=/, file);
    assert.equal(published, source, file);
  }
});

test('tsWorker conserva tamaño razonable y compila sintácticamente', () => {
  const worker = path.join(VS_ROOT, 'language', 'typescript', 'tsWorker.js');
  assert.ok(fs.statSync(worker).size > 5_700_000);
  assert.doesNotThrow(() => new vm.Script(fs.readFileSync(worker, 'utf8'), {
    filename: worker
  }));
});

test('ningún activo está vacío, contiene rutas personales o referencia CDN', () => {
  for (const file of filesUnder(VS_ROOT)) {
    const filename = path.join(VS_ROOT, file);
    assert.ok(fs.statSync(filename).size > 0, file);
    if (/\.(?:js|css)$/.test(file)) {
      const source = fs.readFileSync(filename, 'utf8');
      assert.doesNotMatch(source, /\/home\/mauri|(?:unpkg|jsdelivr|cdnjs)/i, file);
    }
  }
});

test('licencia MIT, avisos y documentación de regeneración están incluidos', () => {
  const license = fs.readFileSync(path.join(VENDOR_ROOT, 'LICENSE.txt'), 'utf8');
  const notices = fs.readFileSync(path.join(VENDOR_ROOT, 'ThirdPartyNotices.txt'), 'utf8');
  const readme = fs.readFileSync(path.join(VENDOR_ROOT, 'README.md'), 'utf8');
  assert.match(license, /The MIT License/);
  assert.match(license, /Microsoft Corporation/);
  assert.ok(notices.length > 1000);
  assert.match(readme, /npm --prefix electron run prepare:monaco/);
});

test('script de preparación verifica versión, licencia, workers y source maps', () => {
  const source = fs.readFileSync(
    path.join(ELECTRON_ROOT, 'scripts', 'prepare-monaco-assets.js'),
    'utf8'
  );
  for (const required of [
    "MONACO_VERSION = '0.52.2'",
    "packageJson.license !== 'MIT'",
    "lockedPackage.integrity",
    "file.endsWith('.map')",
    "'base/worker/workerMain.js'",
    "'language/json/jsonWorker.js'",
    'stripTrailingSourceMapDirective'
  ]) {
    assert.ok(source.includes(required), required);
  }
});
