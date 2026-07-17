'use strict';

const ALLOWED_PROTOCOLS = new Set(['http:', 'ws:']);
const SAFE_PROTOCOL_PATTERN = /^[a-z][a-z0-9+.-]*:$/;

function normalizePort(port) {
  const value = String(port);
  if (!/^[1-9][0-9]{0,4}$/.test(value)) {
    throw new TypeError('El puerto de la política Electron no es válido.');
  }

  const numericPort = Number(value);
  if (numericPort > 65535) {
    throw new TypeError('El puerto de la política Electron no es válido.');
  }
  return value;
}

function parseDestination(rawDestination) {
  if (
    typeof rawDestination !== 'string' ||
    rawDestination.length === 0 ||
    rawDestination.trim() !== rawDestination
  ) {
    return null;
  }

  let url;
  try {
    url = new URL(rawDestination);
  } catch (_error) {
    return null;
  }

  const schemeSeparator = rawDestination.indexOf('://');
  if (schemeSeparator <= 0) {
    return { url, rawAuthority: null };
  }

  const authorityStart = schemeSeparator + 3;
  const authorityTail = rawDestination.slice(authorityStart);
  const authorityEnd = authorityTail.search(/[/?#]/);
  const rawAuthority = authorityEnd === -1
    ? authorityTail
    : authorityTail.slice(0, authorityEnd);

  return { url, rawAuthority };
}

function createLoopbackPolicy(options = {}) {
  const port = normalizePort(options.port || 8000);
  const allowLocalhost = options.allowLocalhost !== false;
  const allowIpv6 = options.allowIpv6 !== false;
  const allowedHosts = new Set(['127.0.0.1']);
  const allowedAuthorities = new Set([`127.0.0.1:${port}`]);

  if (allowLocalhost) {
    allowedHosts.add('localhost');
    allowedAuthorities.add(`localhost:${port}`);
  }
  if (allowIpv6) {
    allowedHosts.add('[::1]');
    allowedAuthorities.add(`[::1]:${port}`);
  }

  function isAllowed(rawDestination) {
    const parsed = parseDestination(rawDestination);
    if (!parsed || parsed.rawAuthority === null) {
      return false;
    }

    const { url, rawAuthority } = parsed;
    if (
      !ALLOWED_PROTOCOLS.has(url.protocol) ||
      url.username !== '' ||
      url.password !== '' ||
      url.port !== port ||
      !allowedHosts.has(url.hostname)
    ) {
      return false;
    }

    // URL normaliza formas IPv4 decimales, octales, hexadecimales y hosts
    // percent-encoded. Exigir también la autoridad literal evita aceptar esas
    // representaciones ambiguas después de que el parser las convierta a loopback.
    return allowedAuthorities.has(rawAuthority.toLowerCase());
  }

  function summarize(rawDestination) {
    const parsed = parseDestination(rawDestination);
    if (!parsed) {
      return Object.freeze({ protocol: 'invalid', destination: 'invalid' });
    }

    const protocol = SAFE_PROTOCOL_PATTERN.test(parsed.url.protocol)
      ? parsed.url.protocol
      : 'invalid';
    const destination = allowedHosts.has(parsed.url.hostname)
      ? 'loopback'
      : 'non-loopback';
    return Object.freeze({ protocol, destination });
  }

  return Object.freeze({
    port,
    allowLocalhost,
    allowIpv6,
    isAllowed,
    summarize,
  });
}

module.exports = {
  createLoopbackPolicy,
  normalizePort,
  parseDestination,
};
