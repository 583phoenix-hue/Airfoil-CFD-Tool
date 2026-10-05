// Page-side API for in-browser inverse design: same inputs, validation,
// messages and result JSON as the backend's /inverse_design/ and
// /inverse_design/baseline/ endpoints, computed in a Web Worker
// (inverseWorker.js) with XFOIL as WebAssembly.

import { AirfoilParseError, parseDatText } from "../airfoilParser.js";
import { LIMITS } from "../xfoil/analysis.js";
import { XfoilUnavailable } from "../xfoil/xfoilClient.js";
import { jsonSafe } from "../aero/index.js";

export class InverseError extends Error {
  constructor(message, status = 500) { super(message); this.status = status; }
}

const fmtInt = (n) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const newWorker = () => new Worker(new URL("./inverseWorker.js", import.meta.url), { type: "module" });
const newPanelWorker = () => new Worker(new URL("./panelWorker.js", import.meta.url), { type: "module" });

/** Extra cores for the optimiser's Jacobian: all but one, at most 7 (the design worker is one more). */
function panelHelperCount() {
  const cores = (typeof navigator !== "undefined" && navigator.hardwareConcurrency) || 2;
  return Math.max(0, Math.min(7, cores - 1));
}

function validateCommon(reynolds, alpha, ncrit) {
  const L = LIMITS;
  if (!(reynolds >= L.minRe && reynolds <= L.maxRe)) throw new InverseError(`Reynolds must be ${fmtInt(L.minRe)} to ${fmtInt(L.maxRe)}`, 400);
  if (!(alpha >= L.minAlpha && alpha <= L.maxAlpha)) throw new InverseError(`Alpha must be ${L.minAlpha} to ${L.maxAlpha} degrees`, 400);
  if (!(ncrit >= L.minNcrit && ncrit <= L.maxNcrit)) throw new InverseError(`NCrit must be ${L.minNcrit} to ${L.maxNcrit.toFixed(1)}`, 400);
}

/** Uploaded seed -> repaired coordinates (main.py _read_seed). */
function readSeed(file) {
  if (!file) return null;
  if (new Blob([file.content]).size > 1024 * 1024) throw new InverseError("File too large", 400);
  try {
    return parseDatText(file.content).coords;
  } catch (e) {
    if (e instanceof AirfoilParseError) throw new InverseError(e.message, 400);
    throw new InverseError(`Couldn't read the seed airfoil: ${e.message}`, 400);
  }
}

function runInWorker(worker, kind, args, onProgress, ports = []) {
  return new Promise((resolve, reject) => {
    worker.onmessage = (ev) => {
      const d = ev.data;
      if (d.type === "progress") { if (onProgress) onProgress(d.fraction, d.message); return; }
      if (d.type === "done") resolve(d.result);
      else if (d.load) reject(new XfoilUnavailable(d.message));
      else reject(new InverseError(d.message, d.status || 500));
    };
    worker.onerror = (ev) => { ev.preventDefault?.(); reject(new XfoilUnavailable(ev.message || "Inverse design worker failed to start")); };
    worker.postMessage({ id: 1, kind, args, ports }, ports);
  });
}

let baselineWorker = null;
let baselineChain = Promise.resolve();

/** The seed's own Cp at the condition (editor starting curve). Resolves to the server's JSON. */
export function runBaselineLocal({ reynolds, alpha, ncrit = 9.0, seedFile = null }) {
  validateCommon(reynolds, alpha, ncrit);
  const seedCoords = readSeed(seedFile);
  const job = baselineChain.then(async () => {
    if (!baselineWorker) baselineWorker = newWorker();
    try {
      const r = await runInWorker(baselineWorker, "baseline", { reynolds, alpha, ncrit, seedCoords });
      return jsonSafe({ ...r, success: true });
    } catch (e) {
      baselineWorker.terminate(); baselineWorker = null; // start fresh next time
      throw e;
    }
  });
  baselineChain = job.catch(() => {});
  return job;
}

/**
 * Full design in its own worker. Returns { promise, cancel }.
 * onProgress(fraction, message) reports the real stage, like the server's progress endpoint.
 */
export function startDesignLocal({ reynolds, alpha, ncrit = 9.0, minThicknessPercent = 0.0, targetUpper, targetLower, seedFile = null },
  onProgress) {
  validateCommon(reynolds, alpha, ncrit);
  if (!(minThicknessPercent >= 0.0 && minThicknessPercent <= 40.0)) throw new InverseError("Minimum thickness must be 0 to 40 % chord", 400);
  if (!Array.isArray(targetUpper) || !Array.isArray(targetLower) || targetUpper.length < 3 || targetLower.length < 3
    || targetUpper.length > 500 || targetLower.length > 500) {
    throw new InverseError("Invalid target curve: each surface needs 3 to 500 points", 400);
  }
  const seedCoords = readSeed(seedFile);
  const worker = newWorker();
  // Panel helpers, each linked to the design worker by its own MessageChannel
  const helpers = [], ports = [];
  try {
    for (let i = 0; i < panelHelperCount(); i++) {
      const h = newPanelWorker(), ch = new MessageChannel();
      h.postMessage({ port: ch.port1 }, [ch.port1]);
      helpers.push(h); ports.push(ch.port2);
    }
  } catch { /* no helpers: the design worker does all the work itself */ }
  const stopAll = () => { worker.terminate(); for (const h of helpers) h.terminate(); };
  let cancelled = false;
  let rejectFn;
  const promise = new Promise((resolve, reject) => {
    rejectFn = reject;
    runInWorker(worker, "design", {
      reynolds, alpha, ncrit, minThickness: minThicknessPercent / 100.0, targetUpper, targetLower, seedCoords,
    }, onProgress, ports).then((r) => resolve(jsonSafe({ ...r, success: true })), reject).finally(stopAll);
  });
  const cancel = () => {
    if (cancelled) return;
    cancelled = true;
    stopAll();
    rejectFn(new InverseError("Design cancelled.", 409));
  };
  return { promise, cancel };
}

export { XfoilUnavailable };
