# XFOIL (WebAssembly build)

`xfoil.js` and `xfoil.wasm` are XFOIL 6.996 by Mark Drela and Harold Youngren,
compiled to WebAssembly by the WebXFOIL project and copied unchanged from the
npm package `webxfoil-wasm@0.1.1`.

AeroLab runs it in the visitor's browser (see `src/lib/xfoil/`), so airfoil
analyses don't use the server.

- License: GNU GPL, version 2 or later (see `COPYING`). AeroLab itself is AGPL-3.0.
- Corresponding source: https://github.com/PR-DC/WebXFOIL (git tag `v0.1.1`),
  upstream XFOIL source https://web.mit.edu/drela/Public/web/xfoil/ — see `SOURCES.md`.
- Other notices: `THIRD_PARTY_NOTICES.md`.

To update: `npm pack webxfoil-wasm@<version>` and copy `dist/xfoil.js`,
`dist/xfoil.wasm`, `COPYING`, `SOURCES.md` and `THIRD_PARTY_NOTICES.md` here.
