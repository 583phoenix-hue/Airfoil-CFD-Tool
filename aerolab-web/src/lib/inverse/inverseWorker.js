// Web Worker for inverse design: the optimisation is seconds of number
// crunching, so it runs here (off the page's thread) together with its own
// XFOIL instance. Cancelling = terminating this worker.
//   in:  { id, kind: "design" | "baseline", args, ports? }  (ports: MessagePorts to panel workers)
//   out: { id, type: "progress", fraction, message }
//        { id, type: "done", result }  |  { id, type: "error", message, status, load }
import { createRunner } from "../xfoil/runner.js";
import { makeResiduals, runInverseDesign, seedBaseline, ValueError } from "./inverse.js";

/**
 * Jacobian pool over the panel workers' ports. This worker takes a share of
 * every batch too, so all requested cores stay busy. Results are the same
 * numbers as computing every point here, one after another.
 */
function makePool(ports) {
  if (!ports || !ports.length) return null;
  let residuals = null, nextId = 0;
  const pending = new Map();
  for (const port of ports) {
    port.onmessage = (e) => { const r = pending.get(e.data.id); pending.delete(e.data.id); if (r) r(e.data.out); };
  }
  return {
    setup(spec) {
      residuals = makeResiduals(spec);
      for (const port of ports) port.postMessage({ type: "setup", spec });
    },
    async evalMany(points, tgt) {
      const k = ports.length + 1;
      const share = Array.from({ length: k }, () => []);
      points.forEach((_, i) => share[i % k].push(i));
      const jobs = ports.map((port, w) => {
        const idx = share[w + 1];
        if (!idx.length) return Promise.resolve([]);
        const id = nextId++;
        return new Promise((resolve) => {
          pending.set(id, resolve);
          port.postMessage({ type: "eval", id, tgt, points: idx.map((i) => points[i]) });
        });
      });
      const out = new Array(points.length);
      for (const i of share[0]) out[i] = residuals(points[i], tgt);
      const theirs = await Promise.all(jobs);
      theirs.forEach((arr, w) => share[w + 1].forEach((i, j) => { out[i] = arr[j]; }));
      return out;
    },
  };
}

const base = new URL("/xfoil/", self.location.href);
let runPromise = null;

function getRunner() {
  if (!runPromise) {
    runPromise = (async () => {
      const wasmUrl = new URL("xfoil.wasm", base);
      const [mod, wasm] = await Promise.all([
        import(/* @vite-ignore */ new URL("xfoil.js", base).href),
        WebAssembly.compileStreaming
          ? WebAssembly.compileStreaming(fetch(wasmUrl)).catch(() =>
            fetch(wasmUrl).then((r) => r.arrayBuffer()).then((b) => WebAssembly.compile(b)))
          : fetch(wasmUrl).then((r) => r.arrayBuffer()).then((b) => WebAssembly.compile(b)),
      ]);
      const run = createRunner(mod.default, wasm);
      // runXfoil(script, files, readNames, timeoutMs): no timeout inside the worker
      // (the page enforces an overall limit and can terminate the worker)
      return (script, files, readNames) => run(script, files, readNames);
    })();
  }
  return runPromise;
}

self.onmessage = async (ev) => {
  const { id, kind, args, ports } = ev.data;
  let runXfoil;
  try {
    runXfoil = await getRunner();
  } catch (e) {
    runPromise = null;
    self.postMessage({ id, type: "error", load: true, message: String((e && e.message) || e) });
    return;
  }
  try {
    let result;
    if (kind === "baseline") {
      result = await seedBaseline(runXfoil, args.reynolds, args.alpha, args.seedCoords, args.ncrit);
    } else {
      result = await runInverseDesign(runXfoil, args.reynolds, args.alpha, args.targetUpper, args.targetLower, {
        seedCoords: args.seedCoords, ncrit: args.ncrit, minThickness: args.minThickness, pool: makePool(ports),
        progress: (fraction, message) => self.postMessage({ id, type: "progress", fraction, message }),
      });
    }
    self.postMessage({ id, type: "done", result });
  } catch (e) {
    self.postMessage({ id, type: "error", load: false, status: e instanceof ValueError ? 400 : 500,
      message: String((e && e.message) || e) });
  }
};
