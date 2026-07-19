'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const Manual = require('../../static/manual.js');

test('manual opens only until it has been dismissed once', () => {
  assert.equal(Manual.shouldOpen({}, Manual.version), true);
  assert.equal(
    Manual.shouldOpen({ onboarding: { manual_version_seen: 0 } }, Manual.version),
    true
  );
  assert.equal(
    Manual.shouldOpen({ onboarding: { manual_version_seen: Manual.version } }, Manual.version),
    false
  );
  assert.equal(
    Manual.shouldOpen({ onboarding: { manual_version_seen: Manual.version + 1 } }, Manual.version),
    false
  );
  assert.equal(
    Manual.shouldOpen({ onboarding: { manual_version_seen: 1 } }, 99),
    false
  );
});

test('manual is local, accessible, and persists dismissal through user config', () => {
  const root = path.resolve(__dirname, '../..');
  const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
  const source = fs.readFileSync(path.join(root, 'static/manual.js'), 'utf8');
  const chrome = fs.readFileSync(path.join(root, 'static/vscode-chrome.js'), 'utf8');
  assert.match(html, /id="manualModal"[^>]+role="dialog"[^>]+aria-modal="true"/);
  assert.match(html, /I\.R\.I\.S\. · ADAPTED USER MANUAL/);
  assert.match(html, /data-manual-role="iris"/);
  assert.match(html, /data-manual-role="ares"/);
  assert.match(html, /data-manual-panel="iris"/);
  assert.match(html, /data-manual-panel="ares"/);
  assert.match(html, /Voice, camera, and local state/);
  assert.match(html, /Files, attachments, and agents/);
  assert.match(html, /Developer workspace/);
  assert.match(html, /Review, approve, and apply/);
  assert.match(html, /<script src="manual\.js"><\/script>/);
  assert.match(source, /\/api\/config\/manual-seen/);
  assert.match(source, /function selectRole\(role\)/);
  assert.match(chrome, /label: 'I\.R\.I\.S\. Manual'/);
  assert.match(chrome, /label: 'A\.R\.E\.S\. Manual'/);
  assert.match(chrome, /GeramManual\.open\('iris'\)/);
  assert.match(chrome, /GeramManual\.open\('ares'\)/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|indexedDB/);
});
