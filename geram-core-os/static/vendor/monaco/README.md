# Monaco Editor local assets

These files are generated from the pinned npm package `monaco-editor@0.52.2`.
The runtime is the package's official AMD distribution under `min/vs`; no CDN,
remote import, bundler, or source map is used. The preparation step removes only
recognized trailing `sourceMappingURL` directives. Identical text inside code,
strings, or internal comments is preserved byte for byte.

Regenerate the directory after installing dependencies:

```sh
npm --prefix electron run prepare:monaco
```

The preparation script verifies the exact package version, MIT license, required
editor and worker modules, lockfile integrity metadata, and absence of source maps
before copying. Do not edit generated runtime files directly. The Microsoft MIT
license and third-party notices are kept beside the runtime.
