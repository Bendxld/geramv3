'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { createLoopbackPolicy, normalizePort } = require('../network-policy');

const policy = createLoopbackPolicy({ port: 8000 });

test('valida estrictamente un puerto Electron configurable', () => {
  assert.equal(normalizePort('49152'), '49152');
  for (const port of ['', '0', '08000', '65536', '8000/path', 'abc']) {
    assert.throws(() => normalizePort(port), /puerto/);
  }
});

test('permite HTTP a 127.0.0.1 en el puerto del HUD', () => {
  assert.equal(policy.isAllowed('http://127.0.0.1:8000/health'), true);
});

test('permite localhost exacto según la política', () => {
  assert.equal(policy.isAllowed('http://localhost:8000/'), true);
  assert.equal(
    createLoopbackPolicy({ port: 8000, allowLocalhost: false })
      .isAllowed('http://localhost:8000/'),
    false,
  );
});

test('trata IPv6 loopback de forma explícita', () => {
  assert.equal(policy.isAllowed('http://[::1]:8000/'), true);
  assert.equal(
    createLoopbackPolicy({ port: 8000, allowIpv6: false })
      .isAllowed('http://[::1]:8000/'),
    false,
  );
});

test('rechaza HTTP externo', () => {
  assert.equal(policy.isAllowed('http://example.invalid/'), false);
});

test('rechaza HTTPS externo y también HTTPS loopback', () => {
  assert.equal(policy.isAllowed('https://example.invalid/'), false);
  assert.equal(policy.isAllowed('https://127.0.0.1:8000/'), false);
});

test('rechaza WebSocket externo', () => {
  assert.equal(policy.isAllowed('ws://example.invalid/socket'), false);
  assert.equal(policy.isAllowed('wss://example.invalid/socket'), false);
});

test('permite WebSocket loopback requerido por el HUD', () => {
  assert.equal(policy.isAllowed('ws://127.0.0.1:8000/ws/hud'), true);
  assert.equal(policy.isAllowed('ws://localhost:8000/ws/hud'), true);
  assert.equal(policy.isAllowed('ws://[::1]:8000/ws/hud'), true);
});

test('rechaza nombres que sólo comienzan como loopback', () => {
  assert.equal(policy.isAllowed('http://127.0.0.1.example.com:8000/'), false);
  assert.equal(policy.isAllowed('http://localhost.example.com:8000/'), false);
});

test('rechaza userinfo aunque el host final sea loopback', () => {
  assert.equal(policy.isAllowed('http://usuario@127.0.0.1:8000/'), false);
  assert.equal(policy.isAllowed('http://usuario:clave@localhost:8000/'), false);
  assert.equal(policy.isAllowed('http://127.0.0.1:8000@example.invalid/'), false);
});

test('rechaza URL inválida o con espacios periféricos', () => {
  assert.equal(policy.isAllowed('esto no es una URL'), false);
  assert.equal(policy.isAllowed(' http://127.0.0.1:8000/'), false);
  assert.equal(policy.isAllowed(''), false);
});

test('rechaza esquemas no autorizados', () => {
  for (const destination of [
    'ftp://127.0.0.1:8000/file',
    'file:///tmp/file',
    'data:text/plain,hello',
    'javascript:alert(1)',
  ]) {
    assert.equal(policy.isAllowed(destination), false);
  }
});

test('exige exactamente el puerto configurado', () => {
  assert.equal(policy.isAllowed('http://127.0.0.1/'), false);
  assert.equal(policy.isAllowed('http://127.0.0.1:8001/'), false);
  assert.equal(policy.isAllowed('http://127.0.0.1:08000/'), false);
});

test('rechaza representaciones IPv4 ambiguas normalizadas por URL', () => {
  for (const destination of [
    'http://2130706433:8000/',
    'http://0177.0.0.1:8000/',
    'http://0x7f000001:8000/',
    'http://%31%32%37.0.0.1:8000/',
  ]) {
    assert.equal(policy.isAllowed(destination), false);
  }
});

test('normaliza con seguridad sólo el uso de mayúsculas del hostname', () => {
  assert.equal(policy.isAllowed('HTTP://LOCALHOST:8000/path'), true);
  assert.equal(policy.isAllowed('http://localhost.:8000/path'), false);
});

test('el resumen nunca incluye hostname, query, fragment ni credenciales', () => {
  const secret = 'token-super-secreto';
  const destination = `https://usuario:${secret}@example.invalid/path?token=${secret}#${secret}`;
  const serialized = JSON.stringify(policy.summarize(destination));
  assert.equal(serialized.includes(secret), false);
  assert.equal(serialized.includes('example.invalid'), false);
  assert.deepEqual(policy.summarize(destination), {
    protocol: 'https:',
    destination: 'non-loopback',
  });
});
