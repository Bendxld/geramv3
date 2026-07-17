'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const SourceControl = require('../../static/source-control.js');
const ROOT = path.resolve(__dirname, '../..');

test('rutas de repositorio se conservan relativas y hunks son navegables', () => {
  assert.equal(SourceControl.joinPath('', 'src/main.py'), 'src/main.py');
  assert.equal(SourceControl.joinPath('project', 'src/main.py'), 'project/src/main.py');
  assert.deepEqual(SourceControl.parseHunks('@@ -1,2 +4,3 @@\ntext\n@@ -9 +20 @@'), [4, 20]);
});

test('dirty guard bloquea sólo archivos seleccionados dentro del repo', () => {
  const documents = new Map([
    ['project/a.py', { path: 'project/a.py', modified: true }],
    ['project/b.py', { path: 'project/b.py', modified: false }],
    ['other.py', { path: 'other.py', modified: true }]
  ]);
  assert.deepEqual(SourceControl.dirtyWorkspacePaths(documents, 'project', ['a.py', 'b.py']), ['project/a.py']);
  assert.deepEqual(SourceControl.dirtyWorkspacePaths(documents, 'project', ['b.py']), []);
});

test('renderer sólo llama contratos Git cerrados y separa diff de ARES', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/source-control.js'), 'utf8');
  for (const endpoint of [
    '/status?', '/diff?', '/stage', '/unstage', '/commit/preview', '/commit/apply',
    '/branches?', '/switch', '/discard/preview', '/discard/apply'
  ]) assert.ok(source.includes(endpoint), endpoint);
  assert.match(source, /WORKTREE → INDEX/);
  assert.match(source, /INDEX → HEAD/);
  assert.match(source, /A\.R\.E\.S\. does not perform these actions/);
  assert.doesNotMatch(source, /innerHTML|eval\s*\(|https?:\/\//);
});

test('UI incluye accesibilidad, refresh, estado, stage múltiple y atajo', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/source-control.js'), 'utf8');
  for (const token of [
    "aria-label', 'Source Control local", 'aria-live', 'Stage selected',
    'Unstage selected', 'Refresh Source Control', "toLowerCase() === 'g'",
    'Switch branch', 'New branch', 'Discard file'
  ]) assert.ok(source.includes(token), token);
  assert.match(source, /\.textContent =/);
});

test('assets locales cargan después de workspace y sin CDN', () => {
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  assert.match(html, /source-control\.css/);
  assert.match(html, /source-control\.js/);
  assert.ok(html.indexOf('workspace.js') < html.indexOf('source-control.js'));
  const css = fs.readFileSync(path.join(ROOT, 'static/source-control.css'), 'utf8');
  assert.match(css, /source-control-panel/);
  assert.doesNotMatch(css, /https?:\/\//);
});

test('workspace expone recarga segura para cambios hechos por Git', () => {
  const workspace = fs.readFileSync(path.join(ROOT, 'static/workspace.js'), 'utf8');
  assert.match(workspace, /function reloadDocuments\(paths\)/);
  assert.match(workspace, /documentState\.modified/);
  assert.match(workspace, /editorAdapter\.setContent\(file\.content/);
  assert.match(workspace, /editorAdapter\.closeDocuments\(removed\)/);
});
