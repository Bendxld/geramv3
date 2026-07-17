'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const Problems = require('../../static/problems.js');
const ROOT = path.resolve(__dirname, '../..');

test('panel conserva sólo errores y warnings con ubicación navegable', () => {
  assert.deepEqual(Problems.normalizeProblems({ problems: [
    { path: 'src/main.ts', message: 'error', severity: 8, line: 2, column: 4, source: 'ts' },
    { path: 'style.css', message: 'warning', severity: 4, line: 1, column: 1 },
    { path: 'ignored.json', message: 'hint', severity: 1, line: 1, column: 1 }
  ] }), [
    { path: 'src/main.ts', message: 'error', severity: 8, line: 2, column: 4, source: 'ts' },
    { path: 'style.css', message: 'warning', severity: 4, line: 1, column: 1, source: '' }
  ]);
});

test('panel usa textContent, navegación local y atajo Ctrl Shift M', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/problems.js'), 'utf8');
  const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
  assert.match(source, /message\.textContent = problem\.message/);
  assert.match(source, /controller\.navigate\(problem\.path, problem\.line, problem\.column\)/);
  assert.match(source, /event\.(?:ctrlKey|metaKey)/);
  assert.match(source, /event\.shiftKey/);
  assert.match(source, /toLowerCase\(\) === 'm'/);
  assert.doesNotMatch(source, /innerHTML|https?:\/\//);
  for (const id of ['workspaceProblems', 'workspaceProblemsToggle', 'workspaceProblemsCount', 'workspaceProblemsList']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /<script src="problems\.js"><\/script>/);
});

test('assets locales contienen servicios reales para cada lenguaje web', () => {
  const expected = {
    'typescript/tsMode.js': ['SuggestAdapter', 'QuickInfoAdapter', 'DefinitionAdapter', 'ReferenceAdapter', 'RenameAdapter', 'FormatAdapter'],
    'html/htmlMode.js': ['CompletionAdapter', 'HoverAdapter', 'DefinitionAdapter', 'ReferenceAdapter', 'RenameAdapter', 'DiagnosticsAdapter'],
    'css/cssMode.js': ['CompletionAdapter', 'HoverAdapter', 'DefinitionAdapter', 'ReferenceAdapter', 'RenameAdapter', 'DiagnosticsAdapter', 'DocumentColorAdapter'],
    'json/jsonMode.js': ['CompletionAdapter', 'HoverAdapter', 'DefinitionAdapter', 'ReferenceAdapter', 'RenameAdapter', 'DiagnosticsAdapter', 'DocumentSymbolAdapter']
  };
  for (const [relative, adapters] of Object.entries(expected)) {
    const source = fs.readFileSync(path.join(ROOT, 'static/vendor/monaco/vs/language', relative), 'utf8');
    for (const adapter of adapters) assert.match(source, new RegExp(adapter), `${relative}: ${adapter}`);
  }
});
