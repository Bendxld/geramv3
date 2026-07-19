'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('first-run setup is versioned, local, and never stores credentials', async () => {
  const root = path.resolve(__dirname, '../..');
  const source = fs.readFileSync(path.join(root, 'static/onboarding.js'), 'utf8');
  const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
  const context = {
    document: { getElementById: () => null },
    navigator: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({ onboarding: { setup_version_seen: 0 }, user_profile: {} }) }),
  };
  context.window = context;
  vm.runInNewContext(source, context, { filename: 'onboarding.js' });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(context.GeramOnboarding.shouldOpen({ onboarding: { setup_version_seen: 0 } }), true);
  assert.equal(context.GeramOnboarding.shouldOpen({ onboarding: { setup_version_seen: 1 } }), false);
  assert.match(html, /id="setupModal"[^>]+role="dialog"/);
  assert.match(source, /\/api\/config\/setup-complete/);
  assert.doesNotMatch(source, /API_KEY|ACCESS_TOKEN|localStorage|sessionStorage/);
});
