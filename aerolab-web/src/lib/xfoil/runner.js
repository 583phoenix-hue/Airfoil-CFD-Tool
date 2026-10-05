// Runs one XFOIL session on the WebAssembly build (public/xfoil/, from the
// webxfoil-wasm package). Every session gets a brand-new XFOIL instance:
// instantiating the already-compiled module takes milliseconds, and it means
// nothing (Fortran state, open files, a crashed run) carries over between runs.

const WORK = "/work";

// When the boundary layer blows up, this XFOIL build keeps marching with NaN
// values and prints millions of "convergence failed ... NaN" lines (the
// native Linux build gives up much sooner). Past these limits the run is
// stopped and counts as not converged, so the next strategy is tried.
const MAX_NAN_LINES = 2000;
const MAX_LINES = 200000;

export class XfoilDiverged extends Error {}

/**
 * factory: the Emscripten module factory exported by xfoil.js
 * wasmModule: a compiled WebAssembly.Module of xfoil.wasm
 * Returns run(script, files, readNames) -> { stdout, stderr, exitCode, files }
 */
export function createRunner(factory, wasmModule) {
  return async function run(script, files = {}, readNames = []) {
    const out = [], err = [];
    let nanLines = 0;
    let diverged = null;
    const onLine = (t) => {
      out.push(t);
      if (t.includes("NaN") && ++nanLines > MAX_NAN_LINES) diverged = "XFOIL diverged (NaN)";
      else if (out.length > MAX_LINES) diverged = "XFOIL produced too much output";
      // Throwing here aborts this (throwaway) XFOIL instance.
      if (diverged) throw new XfoilDiverged(diverged);
    };
    const stdin = new TextEncoder().encode(script.endsWith("\n") ? script : `${script}\n`);
    let pos = 0;
    const mod = await factory({
      noInitialRun: true,
      noExitRuntime: true,
      print: onLine,
      printErr: (t) => err.push(t),
      stdin: () => (pos < stdin.length ? stdin[pos++] : null),
      instantiateWasm(imports, receive) {
        WebAssembly.instantiate(wasmModule, imports).then((inst) => receive(inst, wasmModule));
        return {};
      },
    });
    const FS = mod.FS;
    FS.mkdir(WORK);
    FS.chdir(WORK);
    for (const [name, text] of Object.entries(files)) FS.writeFile(`${WORK}/${name}`, text);

    let exitCode = 0;
    try {
      mod.callMain([]);
    } catch (e) {
      if (e && e.name === "ExitStatus") exitCode = e.status || 0;
      else if (diverged) { exitCode = -2; err.push(diverged); }
      else { exitCode = -1; err.push(String((e && e.message) || e)); }
    }

    const outFiles = {};
    for (const name of readNames) {
      const path = `${WORK}/${name}`;
      outFiles[name] = FS.analyzePath(path).exists ? FS.readFile(path, { encoding: "utf8" }) : null;
    }
    return { stdout: out.join("\n"), stderr: err.join("\n"), exitCode, files: outFiles };
  };
}
