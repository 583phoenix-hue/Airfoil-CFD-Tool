// Web Worker that runs XFOIL sessions off the main thread, so the page stays
// responsive while XFOIL works. Messages:
//   in:  { id, script, files: { name: text }, read: [name, ...] }  or  { id, warmup: true }
//   out: { id, ok: true, result: { stdout, stderr, exitCode, files } | null }
//        { id, ok: false, error, load }   (load: true = XFOIL itself couldn't be loaded)
import { createRunner } from "./runner.js";

const base = new URL("/xfoil/", self.location.href);
let runnerPromise = null;

function getRunner() {
  if (!runnerPromise) {
    runnerPromise = (async () => {
      const wasmUrl = new URL("xfoil.wasm", base);
      const [mod, wasm] = await Promise.all([
        import(/* @vite-ignore */ new URL("xfoil.js", base).href),
        WebAssembly.compileStreaming
          ? WebAssembly.compileStreaming(fetch(wasmUrl)).catch(() =>
            fetch(wasmUrl).then((r) => r.arrayBuffer()).then((b) => WebAssembly.compile(b)))
          : fetch(wasmUrl).then((r) => r.arrayBuffer()).then((b) => WebAssembly.compile(b)),
      ]);
      return createRunner(mod.default, wasm);
    })();
  }
  return runnerPromise;
}

self.onmessage = async (ev) => {
  const { id, script, files, read, warmup } = ev.data;
  let run;
  try {
    run = await getRunner();
  } catch (e) {
    runnerPromise = null;
    self.postMessage({ id, ok: false, load: true, error: String((e && e.message) || e) });
    return;
  }
  if (warmup) { self.postMessage({ id, ok: true, result: null }); return; }
  try {
    self.postMessage({ id, ok: true, result: await run(script, files, read) });
  } catch (e) {
    self.postMessage({ id, ok: false, load: false, error: String((e && e.message) || e) });
  }
};
