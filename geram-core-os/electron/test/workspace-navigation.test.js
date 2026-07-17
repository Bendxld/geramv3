'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const Navigation = require('../../static/workspace-navigation.js');
const ROOT = path.resolve(__dirname, '../..');

test('fuzzy matching es incremental, determinista y favorece basename compacto', () => {
  assert.equal(Navigation.fuzzyScore('', 'src/main.py'), 0);
  assert.equal(Navigation.fuzzyScore('zzz', 'src/main.py'), null);
  assert.ok(Navigation.fuzzyScore('main', 'src/main.py') < Navigation.fuzzyScore('main', 'long/path/main-helper.py'));
  assert.ok(Navigation.fuzzyScore('smp', 'src/main.py') < Navigation.fuzzyScore('smp', 'some/long/main.py'));
});

test('historial recorta avance, vuelve y avanza sin duplicar ubicación', () => {
  const history = new Navigation.NavigationHistory(3);
  history.push({ path: 'a.py', line: 1, column: 1 });
  history.push({ path: 'b.js', line: 2, column: 3 });
  history.push({ path: 'b.js', line: 2, column: 3 });
  assert.equal(history.back().path, 'a.py');
  assert.equal(history.forward().path, 'b.js');
  history.back(); history.push({ path: 'c.py', line: 4, column: 1 });
  assert.equal(history.forward(), null);
});

test('filtros include exclude se normalizan y acotan', () => {
  assert.deepEqual(Navigation.filters('src/*.js, tests/*, , docs/**'), ['src/*.js', 'tests/*', 'docs/**']);
  assert.equal(Navigation.filters(Array(30).fill('*.js').join(',')).length, 16);
});

test('UI declara Quick Open, búsqueda, reemplazo aprobado y navegación completa', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/workspace-navigation.js'), 'utf8');
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  for (const token of [
    "key === 'p'", "key === 'f'", "key === 't'", "key === 'o'",
    "event.key === 'ArrowLeft'", "event.key === 'ArrowRight'",
    '/api/navigation/search', '/api/navigation/replacements/preview', '/api/navigation/replacements/apply',
    "editor.action.quickOutline", 'getNavigationTree', 'workspaceSymbols'
  ]) assert.ok(source.includes(token), token);
  for (const id of [
    'workspaceNavigation', 'workspaceNavigationInput', 'workspaceSearchCase', 'workspaceSearchWord',
    'workspaceSearchRegex', 'workspaceSearchInclude', 'workspaceSearchExclude',
    'workspaceReplacementPreview', 'workspaceReplacementApply', 'workspaceNavigationCancel'
  ]) assert.match(html, new RegExp(`id="${id}"`));
});

test('resultados usan textContent, fetch abortable y no permiten shell o recursos externos', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/workspace-navigation.js'), 'utf8');
  assert.match(source, /\.textContent =/);
  assert.match(source, /new windowObject\.AbortController/);
  assert.match(source, /aborter\.abort\(\)/);
  assert.doesNotMatch(source, /innerHTML|child_process|eval\s*\(|https?:\/\//);
});

test('assets de navegación son locales y cargan después de Monaco y Pyright', () => {
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  assert.match(html, /<link rel="stylesheet" href="workspace-navigation\.css">/);
  assert.match(html, /<script src="workspace-navigation\.js"><\/script>/);
  assert.ok(html.indexOf('python-lsp.js') < html.indexOf('workspace-navigation.js'));
  const css = fs.readFileSync(path.join(ROOT, 'static/workspace-navigation.css'), 'utf8');
  assert.match(css, /workspace-search-options\[hidden\].*display:none/);
});
