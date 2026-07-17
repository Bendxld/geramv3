'use strict';

const fs = require('fs');
const path = require('path');

const MONACO_VERSION = '0.52.2';
const electronRoot = path.resolve(__dirname, '..');
const repositoryRoot = path.resolve(electronRoot, '..');
const packageRoot = path.join(electronRoot, 'node_modules', 'monaco-editor');
const sourceRoot = path.join(packageRoot, 'min', 'vs');
const destinationRoot = path.join(repositoryRoot, 'static', 'vendor', 'monaco');
const destinationVs = path.join(destinationRoot, 'vs');
const packageLockPath = path.join(electronRoot, 'package-lock.json');

function readPackageMetadata() {
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'),
  );
  const packageLock = JSON.parse(fs.readFileSync(packageLockPath, 'utf8'));
  const lockedPackage = packageLock.packages['node_modules/monaco-editor'];
  if (
    packageJson.version !== MONACO_VERSION ||
    packageJson.license !== 'MIT' ||
    !lockedPackage ||
    lockedPackage.version !== MONACO_VERSION ||
    lockedPackage.license !== 'MIT' ||
    !/^sha512-[A-Za-z0-9+/=]+$/.test(lockedPackage.integrity || '')
  ) {
    throw new Error('La versión o licencia instalada de Monaco no coincide con la fijada.');
  }
  return {
    version: packageJson.version,
    license: packageJson.license,
    integrity: lockedPackage.integrity,
  };
}

function collectFiles(root, relative = '') {
  const directory = path.join(root, relative);
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const child = path.join(relative, entry.name);
    return entry.isDirectory() ? collectFiles(root, child) : [child];
  });
}

function verifyRuntime(files) {
  if (files.some((file) => file.endsWith('.map'))) {
    throw new Error('La distribución local de Monaco no debe incluir source maps.');
  }
  for (const required of [
    'loader.js',
    'editor/editor.main.js',
    'editor/editor.main.css',
    'base/worker/workerMain.js',
    'language/json/jsonWorker.js',
    'language/css/cssWorker.js',
    'language/html/htmlWorker.js',
    'language/typescript/tsWorker.js',
  ]) {
    if (!files.includes(required)) {
      throw new Error('Falta un activo requerido en la distribución local de Monaco.');
    }
  }
}

function stripTrailingSourceMapDirective(content) {
  if (typeof content !== 'string') {
    throw new TypeError('El contenido del activo debe ser texto.');
  }

  const lineDirective =
    /(?:\r?\n)?[ \t]*\/\/[#@][ \t]*sourceMappingURL=[ \t]*\S+[ \t]*(?:\r?\n)?[ \t]*$/;
  if (lineDirective.test(content)) {
    return content.replace(lineDirective, '\n');
  }

  const blockDirective =
    /[ \t]*\/\*[#@][ \t]*sourceMappingURL=[ \t]*(?:[^*\s]|\*(?!\/))+[ \t]*\*\/[ \t]*(?:\r?\n)?[ \t]*$/;
  const match = blockDirective.exec(content);
  if (!match) { return content; }

  const prefix = content.slice(0, match.index).replace(/[ \t]+$/, '');
  const hadFinalNewline = /\r?\n[ \t]*$/.test(content);
  return hadFinalNewline && !/\r?\n$/.test(prefix) ? prefix + '\n' : prefix;
}

function validateRelativeAssetPath(relative) {
  if (
    typeof relative !== 'string' ||
    !relative ||
    path.isAbsolute(relative) ||
    relative.split(/[\\/]/).some((part) => !part || part === '.' || part === '..')
  ) {
    throw new Error('La ruta del activo Monaco no es relativa y canónica.');
  }
}

function copyRuntimeFiles(files, fromRoot = sourceRoot, toRoot = destinationVs) {
  for (const relative of files) {
    validateRelativeAssetPath(relative);
    const sourceFilename = path.join(fromRoot, relative);
    const destinationFilename = path.join(toRoot, relative);
    const source = fs.readFileSync(sourceFilename);
    let published = source;
    if (/\.(?:js|css)$/.test(relative)) {
      published = Buffer.from(stripTrailingSourceMapDirective(source.toString('utf8')), 'utf8');
      if (stripTrailingSourceMapDirective(published.toString('utf8')) !== published.toString('utf8')) {
        throw new Error('No se pudo retirar una directiva final de source map de Monaco.');
      }
    }
    fs.mkdirSync(path.dirname(destinationFilename), { recursive: true });
    fs.writeFileSync(destinationFilename, published);
  }
}

function prepareSelectedAssets(selectedFiles) {
  readPackageMetadata();
  const sourceFiles = collectFiles(sourceRoot);
  verifyRuntime(sourceFiles);
  for (const relative of selectedFiles) {
    if (!sourceFiles.includes(relative)) {
      throw new Error('El activo solicitado no existe en el paquete Monaco fijado.');
    }
  }
  copyRuntimeFiles(selectedFiles);
}

function prepareAssets() {
  const metadata = readPackageMetadata();
  const sourceFiles = collectFiles(sourceRoot);
  verifyRuntime(sourceFiles);

  fs.mkdirSync(destinationRoot, { recursive: true });
  fs.rmSync(destinationVs, { recursive: true, force: true });
  copyRuntimeFiles(sourceFiles);
  fs.copyFileSync(path.join(packageRoot, 'LICENSE'), path.join(destinationRoot, 'LICENSE.txt'));
  fs.copyFileSync(
    path.join(packageRoot, 'ThirdPartyNotices.txt'),
    path.join(destinationRoot, 'ThirdPartyNotices.txt'),
  );
  fs.writeFileSync(
    path.join(destinationRoot, 'manifest.json'),
    `${JSON.stringify({
      package: 'monaco-editor',
      version: metadata.version,
      source: 'npm package monaco-editor',
      license: 'MIT',
      runtime: 'min/vs',
      asset_count: sourceFiles.length,
      source_maps: false,
    }, null, 2)}\n`,
    'utf8',
  );
}

if (require.main === module) {
  const selectedFiles = process.argv.slice(2);
  if (selectedFiles.length) {
    prepareSelectedAssets(selectedFiles);
  } else {
    prepareAssets();
  }
}

module.exports = {
  MONACO_VERSION,
  collectFiles,
  copyRuntimeFiles,
  prepareAssets,
  prepareSelectedAssets,
  readPackageMetadata,
  stripTrailingSourceMapDirective,
  verifyRuntime,
};
