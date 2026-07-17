'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  copyRuntimeFiles,
  stripTrailingSourceMapDirective,
} = require('../scripts/prepare-monaco-assets.js');

function sha256(filename) {
  return crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
}

test('retira una directiva //# sourceMappingURL final', () => {
  assert.equal(
    stripTrailingSourceMapDirective('const value = 1;\n//# sourceMappingURL=app.js.map'),
    'const value = 1;\n',
  );
});

test('retira una directiva //@ sourceMappingURL final', () => {
  assert.equal(
    stripTrailingSourceMapDirective('const value = 1;\n//@ sourceMappingURL=app.js.map\n'),
    'const value = 1;\n',
  );
});

test('retira una directiva de bloque final reconocida', () => {
  assert.equal(
    stripTrailingSourceMapDirective('body {}\n/*# sourceMappingURL=style.css.map */\n'),
    'body {}\n',
  );
});

test('conserva sourceMappingURL dentro de literales', () => {
  const source = 'const marker = "sourceMappingURL=";\nconst tail = true;\n';
  assert.equal(stripTrailingSourceMapDirective(source), source);
});

test('conserva comentarios internos y todo el contenido posterior', () => {
  const source = [
    'const before = true;',
    '//# sourceMappingURL=internal-example.map',
    'const after = "must survive";',
    '',
  ].join('\n');
  assert.equal(stripTrailingSourceMapDirective(source), source);
  assert.match(stripTrailingSourceMapDirective(source), /must survive/);
});

test('un archivo sin directiva final permanece idéntico', () => {
  const source = 'function safe() { return "unchanged"; }\n';
  assert.equal(stripTrailingSourceMapDirective(source), source);
});

test('la transformación es idempotente', () => {
  const source = 'const value = 1;\n//# sourceMappingURL=app.js.map';
  const once = stripTrailingSourceMapDirective(source);
  assert.equal(stripTrailingSourceMapDirective(once), once);
});

test('un archivo grande con texto interno no se trunca', () => {
  const source = [
    'x'.repeat(6_000_000),
    'const marker = "sourceMappingURL=";',
    'const finalStatement = true;',
    '',
  ].join('\n');
  const result = stripTrailingSourceMapDirective(source);
  assert.equal(result.length, source.length);
  assert.equal(result, source);
  assert.match(result.slice(-80), /finalStatement = true/);
});

test('la copia selectiva es reproducible al ejecutarse dos veces', (context) => {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'geram-monaco-assets-'));
  context.after(() => fs.rmSync(temporaryRoot, { recursive: true, force: true }));
  const sourceRoot = path.join(temporaryRoot, 'source');
  const destinationRoot = path.join(temporaryRoot, 'destination');
  fs.mkdirSync(path.join(sourceRoot, 'nested'), { recursive: true });
  fs.writeFileSync(
    path.join(sourceRoot, 'fixture.js'),
    'const marker = "sourceMappingURL=";\n//# sourceMappingURL=fixture.js.map',
  );
  fs.writeFileSync(
    path.join(sourceRoot, 'nested', 'fixture.css'),
    'body {}\n/*# sourceMappingURL=fixture.css.map */\n',
  );

  const files = ['fixture.js', 'nested/fixture.css'];
  copyRuntimeFiles(files, sourceRoot, destinationRoot);
  const firstHashes = files.map((file) => sha256(path.join(destinationRoot, file)));
  copyRuntimeFiles(files, sourceRoot, destinationRoot);
  const secondHashes = files.map((file) => sha256(path.join(destinationRoot, file)));

  assert.deepEqual(secondHashes, firstHashes);
  assert.match(fs.readFileSync(path.join(destinationRoot, 'fixture.js'), 'utf8'), /marker/);
});
