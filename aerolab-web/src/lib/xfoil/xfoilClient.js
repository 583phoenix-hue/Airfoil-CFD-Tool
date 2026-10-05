// Browser-side XFOIL: a small pool of Web Workers (xfoilWorker.js), a queue,
// and a per-run time limit. A run that goes over its limit has its worker
// terminated and replaced, the same way the server killed a stuck XFOIL.

import { analyzeAirfoil, XfoilTimeout } from "./analysis.js";

export class XfoilUnavailable extends Error {}

// Up to 3 XFOIL runs at once (e.g. control reversal's three polars), but
// leave a core for the page on small machines.
const CORES = (typeof navigator !== "undefined" && navigator.hardwareConcurrency) || 2;
const POOL_SIZE = Math.min(3, Math.max(2, CORES - 1));

let nextId = 1;
const slots = [];        // { worker, busy }
const queue = [];        // pending jobs
let unavailable = null;  // set once XFOIL failed to load in this browser

function newWorker() {
  return new Worker(new URL("./xfoilWorker.js", import.meta.url), { type: "module" });
}

function send(slot, msg, timeoutMs) {
  return new Promise((resolve, reject) => {
    let timer = null;
    const done = () => {
      clearTimeout(timer);
      slot.worker.removeEventListener("message", onMsg);
      slot.worker.removeEventListener("error", onErr);
    };
    const onMsg = (ev) => {
      if (ev.data.id !== msg.id) return;
      done();
      if (ev.data.ok) resolve(ev.data.result);
      else reject(ev.data.load ? new XfoilUnavailable(ev.data.error) : new Error(ev.data.error));
    };
    const onErr = (ev) => {
      done();
      ev.preventDefault?.();
      slot.worker.terminate();
      slot.worker = newWorker();
      reject(new XfoilUnavailable(ev.message || "XFOIL worker failed to start"));
    };
    slot.worker.addEventListener("message", onMsg);
    slot.worker.addEventListener("error", onErr);
    if (timeoutMs) {
      timer = setTimeout(() => {
        done();
        slot.worker.terminate();          // the only way to stop a running XFOIL
        slot.worker = newWorker();
        reject(new XfoilTimeout(`XFOIL timed out after ${Math.round(timeoutMs / 1000)} seconds`));
      }, timeoutMs);
    }
    slot.worker.postMessage(msg);
  });
}

function pump() {
  while (queue.length) {
    let slot = slots.find((s) => !s.busy);
    if (!slot && slots.length < POOL_SIZE) {
      slot = { worker: newWorker(), busy: false };
      slots.push(slot);
    }
    if (!slot) return;
    const job = queue.shift();
    slot.busy = true;
    send(slot, job.msg, job.timeoutMs)
      .then(job.resolve, job.reject)
      .finally(() => { slot.busy = false; pump(); });
  }
}

function enqueue(msg, timeoutMs) {
  if (unavailable) return Promise.reject(unavailable);
  return new Promise((resolve, reject) => {
    queue.push({ msg: { ...msg, id: nextId++ }, timeoutMs, resolve, reject: (e) => {
      if (e instanceof XfoilUnavailable) unavailable = e;
      reject(e);
    } });
    pump();
  });
}

/** One XFOIL session. Resolves to { stdout, stderr, exitCode, files }. */
export function runXfoilSession(script, files, read, timeoutMs) {
  return enqueue({ script, files, read }, timeoutMs);
}

/** Start downloading/compiling XFOIL early (e.g. when the Analysis page opens). */
export function warmUpXfoil() {
  if (typeof Worker === "undefined" || typeof WebAssembly === "undefined") return Promise.resolve(false);
  // Load 15 s budget: on a slow connection the 1 MB download can take a moment.
  return enqueue({ warmup: true }, 15000).then(() => true, () => false);
}

/** True if this browser can run XFOIL locally (false after a load failure). */
export function localXfoilSupported() {
  return !unavailable && typeof Worker !== "undefined" && typeof WebAssembly !== "undefined";
}

/** Analyse one airfoil file in the browser; same result shape as the server. */
export function analyzeInBrowser(fileText, params) {
  return analyzeAirfoil(runXfoilSession, fileText, params);
}
