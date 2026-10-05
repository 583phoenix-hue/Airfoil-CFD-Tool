// Inverse design: find the airfoil whose surface pressure matches a drawn
// target Cp(x/c). JavaScript port of the backend's inverse_design.py (SU2-
// style Cp matching: CST shape variables, linear-vortex panel method, bounded
// trust-region least squares, viscous XFOIL defect correction). See that file
// for the full background; keep the two in step.
//
// `runXfoil(script, files, readNames, timeoutMs)` is injected.

import { pyFloat } from "../airfoilParser.js";
import { pyStr, XfoilTimeout } from "../xfoil/analysis.js";
import { interp, linspace, pyFixed, pyRound } from "../aero/numerics.js";
import { lstsq } from "./linalg.js";
import { leastSquaresTrf } from "./lsq.js";
import { PANEL_WASM, PANEL_WASM_SIMD } from "./panelKernel.js";

export const N_SURF = 90;
export const CST_ORDERS = [8, 10, 12];
export const SEED_FIT_TOL = 5e-4;
export const EDITOR_POINTS = 41;
export const MAX_CP = 1.0;

const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now()) / 1000;
const argsortX = (rows) => rows.map((r, i) => [r[0], i]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((p) => rows[p[1]]);
const argminFirst = (a) => { let k = 0; for (let i = 1; i < a.length; i++) if (a[i] < a[k]) k = i; return k; };
const argmaxFirst = (a) => { let k = 0; for (let i = 1; i < a.length; i++) if (a[i] > a[k]) k = i; return k; };
const maxOf = (a) => a.reduce((m, v) => (v > m ? v : m), -Infinity);
const diff = (a) => { const o = new Float64Array(a.length - 1); for (let i = 0; i < o.length; i++) o[i] = a[i + 1] - a[i]; return o; };

// ── Linear-strength vortex panel method (Katz & Plotkin VOR2DL) ─────────────
// This is the optimiser's inner loop (thousands of calls per design), so it
// works on flat typed arrays and avoids hypot/sqrt where a squared form will do.

/** In-place LU solve with partial pivoting of the m x m row-major matrix M; x holds b on entry. */
function solveFlat(M, x, m) {
  for (let k = 0; k < m; k++) {
    let p = k, big = Math.abs(M[k * m + k]);
    for (let i = k + 1; i < m; i++) { const v = Math.abs(M[i * m + k]); if (v > big) { big = v; p = i; } }
    if (big === 0) throw new Error("Singular matrix");
    if (p !== k) {
      for (let j = 0; j < m; j++) { const t = M[k * m + j]; M[k * m + j] = M[p * m + j]; M[p * m + j] = t; }
      const t = x[k]; x[k] = x[p]; x[p] = t;
    }
    const kb = k * m, piv = M[kb + k];
    for (let i = k + 1; i < m; i++) {
      const ib = i * m, f = M[ib + k] / piv;
      if (f === 0) continue;
      M[ib + k] = f;
      for (let j = k + 1; j < m; j++) M[ib + j] -= f * M[kb + j];
      x[i] -= f * x[k];
    }
  }
  for (let k = m - 1; k >= 0; k--) {
    const kb = k * m;
    let s = x[k];
    for (let j = k + 1; j < m; j++) s -= M[kb + j] * x[j];
    x[k] = s / M[kb + k];
  }
  return x;
}

// The same solver in C (native/panel.c), compiled to WebAssembly: about 2.5x
// faster and bit-identical (it calls JavaScript's own Math.atan2/log/cos/sin).
// Only used inside workers; anywhere it can't load, the JS version below runs.
function loadWasmPanel() {
  try {
    if (typeof WebAssembly === "undefined") return null;
    const bytes = (b64) => Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
    const simd = bytes(PANEL_WASM_SIMD);
    const mod = new WebAssembly.Module(WebAssembly.validate(simd) ? simd : bytes(PANEL_WASM));
    const { reserve, panel_cp: run, memory } = new WebAssembly.Instance(mod, {
      env: { atan2: Math.atan2, log: Math.log, cos: Math.cos, sin: Math.sin },
    }).exports;
    return (xs, ys, alphaDeg) => {
      const N = xs.length, n = N - 1, m = N;
      const ptr = reserve(4 * N + 9 * n + m + m * m + n * m);
      if (!ptr) return null;
      const H = new Float64Array(memory.buffer, ptr, 2 * N + 3 * n);
      for (let i = 0; i < N; i++) { H[i] = xs[i]; H[N + i] = ys[i]; }
      if (run(N, alphaDeg)) throw new Error("Singular matrix");
      return {
        cp: Array.from(H.subarray(2 * N, 2 * N + n)),
        xc: Array.from(H.subarray(2 * N + n, 2 * N + 2 * n)),
        yc: Array.from(H.subarray(2 * N + 2 * n, 2 * N + 3 * n)),
      };
    };
  } catch {
    return null;
  }
}
const wasmPanel = typeof window === "undefined" ? loadWasmPanel() : null;

/** Coordinates in Selig order. Returns { xc, yc, cp } at panel midpoints, Selig order. */
export function panelCp(xs, ys, alphaDeg) {
  if (wasmPanel) {
    const r = wasmPanel(xs, ys, alphaDeg);
    if (r) return r;
  }
  return panelCpJs(xs, ys, alphaDeg);
}

/** Pure-JavaScript panel solver (fallback; same numbers as the WebAssembly one). */
export function panelCpJs(xs, ys, alphaDeg) {
  const N = xs.length, n = N - 1, m = n + 1;
  const x = new Float64Array(N), y = new Float64Array(N);
  for (let i = 0; i < N; i++) { x[i] = xs[N - 1 - i]; y[i] = ys[N - 1 - i]; }
  const a = alphaDeg * (Math.PI / 180);
  const xc = new Float64Array(n), yc = new Float64Array(n), len = new Float64Array(n);
  const cj = new Float64Array(n), sj = new Float64Array(n);
  for (let j = 0; j < n; j++) {
    const ddx = x[j + 1] - x[j], ddy = y[j + 1] - y[j];
    const th = Math.atan2(ddy, ddx);
    xc[j] = 0.5 * (x[j] + x[j + 1]); yc[j] = 0.5 * (y[j] + y[j + 1]);
    cj[j] = Math.cos(th); sj[j] = Math.sin(th);
    len[j] = Math.sqrt(ddx * ddx + ddy * ddy);
  }
  const A = new Float64Array(m * m), B = new Float64Array(n * m);
  const inv2pi = 1 / (2 * Math.PI);
  for (let i = 0; i < n; i++) {
    const ci = cj[i], si = sj[i], rb = i * m, xci = xc[i], yci = yc[i];
    for (let j = 0; j < n; j++) {
      const dx = xci - x[j], dy = yci - y[j], c = cj[j], s = sj[j];
      const X = dx * c + dy * s, Y = -dx * s + dy * c, X2 = len[j];
      let U1L, U2L, W1L, W2L;
      if (i === j) {
        U1L = -0.5 * (X - X2) / X2; U2L = 0.5 * X / X2;
        W1L = -inv2pi; W2L = inv2pi;
      } else {
        const XmX2 = X - X2, Y2 = Y * Y;
        const dTH = Math.atan2(Y, XmX2) - Math.atan2(Y, X);
        const LN = 0.5 * Math.log((XmX2 * XmX2 + Y2) / (X * X + Y2));
        const tp = inv2pi / X2;
        U1L = -(Y * LN + X * dTH - X2 * dTH) * tp; U2L = (Y * LN + X * dTH) * tp;
        W1L = -((X2 - Y * dTH) + X * LN - X2 * LN) * tp; W2L = ((X2 - Y * dTH) + X * LN) * tp;
      }
      const u1 = U1L * c - W1L * s, w1 = U1L * s + W1L * c;
      const u2 = U2L * c - W2L * s, w2 = U2L * s + W2L * c;
      A[rb + j] += -u1 * si + w1 * ci; B[rb + j] += u1 * ci + w1 * si;
      A[rb + j + 1] += -u2 * si + w2 * ci; B[rb + j + 1] += u2 * ci + w2 * si;
    }
  }
  A[n * m] = 1.0; A[n * m + n] = 1.0; // Kutta condition
  const ca = Math.cos(a), sa = Math.sin(a);
  const g = new Float64Array(m);
  for (let i = 0; i < n; i++) g[i] = ca * sj[i] - sa * cj[i];
  solveFlat(A, g, m);
  const cp = new Array(n), xo = new Array(n), yo = new Array(n);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    const rb = i * m;
    for (let j = 0; j < m; j++) sum += B[rb + j] * g[j];
    const vt = sum + ca * cj[i] + sa * sj[i];
    cp[n - 1 - i] = 1.0 - vt * vt; xo[n - 1 - i] = xc[i]; yo[n - 1 - i] = yc[i];
  }
  return { xc: xo, yc: yo, cp };
}

/** Lift coefficient from integrating panel-midpoint Cp (Selig order). */
export function pressureCl(xs, ys, cpMid, alphaDeg) {
  let fx = 0, fy = 0;
  for (let i = 0; i < cpMid.length; i++) {
    fx += cpMid[i] * (ys[i + 1] - ys[i]);
    fy -= cpMid[i] * (xs[i + 1] - xs[i]);
  }
  const a = alphaDeg * (Math.PI / 180);
  return -(fy * Math.cos(a) - fx * Math.sin(a));
}

// ── Geometry: seeds and CST ─────────────────────────────────────────────────
export const cosineX = (n) => linspace(0, Math.PI, n).map((t) => 0.5 * (1 - Math.cos(t)));

export function naca4(code = "0012", n = 200) {
  const m = Number(code[0]) / 100, p = Number(code[1]) / 10, t = Number(code.slice(2)) / 100;
  const x = cosineX(n);
  const yt = x.map((xi) => 5 * t * (0.2969 * Math.sqrt(xi) - 0.126 * xi - 0.3516 * xi ** 2 + 0.2843 * xi ** 3 - 0.1036 * xi ** 4));
  const yc = x.map((xi) => (m === 0 ? 0 : xi < p ? m / p ** 2 * (2 * p * xi - xi ** 2) : m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * xi - xi ** 2)));
  const dyc = x.map((xi) => (m === 0 ? 0 : xi < p ? 2 * m / p ** 2 * (p - xi) : 2 * m / (1 - p) ** 2 * (p - xi)));
  const thv = dyc.map(Math.atan);
  const xu = x.map((xi, i) => xi - yt[i] * Math.sin(thv[i])), yu = yc.map((v, i) => v + yt[i] * Math.cos(thv[i]));
  const xl = x.map((xi, i) => xi + yt[i] * Math.sin(thv[i])), yl = yc.map((v, i) => v - yt[i] * Math.cos(thv[i]));
  return [xu.slice().reverse().concat(xl.slice(1)), yu.slice().reverse().concat(yl.slice(1))];
}

export function defaultSeed() {
  const [x, y] = naca4("0012", 100);
  return x.map((xi, i) => [xi, y[i]]);
}

/** Selig order, LE at (0,0), TE midpoint at (1,0), upper surface first. Returns [coords, ile]. */
export function normalizeSeed(coords) {
  let c = coords.map((p) => [p[0], p[1]]);
  if (c.length < 10) throw new ValueError("Seed airfoil needs at least 10 points");
  const te = [0.5 * (c[0][0] + c[c.length - 1][0]), 0.5 * (c[0][1] + c[c.length - 1][1])];
  let ile = argmaxFirst(c.map((p) => Math.hypot(p[0] - te[0], p[1] - te[1])));
  const le = c[ile];
  const ang = Math.atan2(te[1] - le[1], te[0] - le[0]);
  const chord = Math.hypot(te[0] - le[0], te[1] - le[1]);
  const r00 = Math.cos(-ang), r01 = -Math.sin(-ang), r10 = Math.sin(-ang), r11 = Math.cos(-ang);
  c = c.map(([px, py]) => {
    const dx = px - le[0], dy = py - le[1];
    return [(dx * r00 + dy * r01) / chord, (dx * r10 + dy * r11) / chord];
  });
  const mean = (arr) => arr.reduce((s, p) => s + p[1], 0) / arr.length;
  if (mean(c.slice(0, ile + 1)) < mean(c.slice(ile))) {
    c = c.slice().reverse();
    ile = c.length - 1 - ile;
  }
  return [c, ile];
}

export class ValueError extends Error {}

const comb = (n, k) => { let r = 1; for (let i = 1; i <= k; i++) r = (r * (n - k + i)) / i; return Math.round(r); };
export function bern(xs, n) {
  return xs.map((x) => { const row = new Float64Array(n + 1); for (let i = 0; i <= n; i++) row[i] = comb(n, i) * x ** i * (1 - x) ** (n - i); return row; });
}

export class CST {
  constructor(order, dzU = 0.0, dzL = 0.0) {
    this.n = order;
    this.xs = cosineX(N_SURF);
    this.B = bern(this.xs, order);
    this.C = this.xs.map((x) => Math.sqrt(x) * (1 - x));
    this.dzU = dzU; this.dzL = dzL;
    this.nvar = 2 * (order + 1);
  }

  surfaces(p) {
    const k = this.n + 1;
    const yu = new Array(N_SURF), yl = new Array(N_SURF);
    for (let i = 0; i < N_SURF; i++) {
      const b = this.B[i];
      let su = 0, sl = 0;
      for (let j = 0; j < k; j++) { su += b[j] * p[j]; sl += b[j] * p[k + j]; }
      yu[i] = this.C[i] * su + this.xs[i] * this.dzU;
      yl[i] = this.C[i] * sl + this.xs[i] * this.dzL;
    }
    return [yu, yl];
  }

  coords(p) {
    const [yu, yl] = this.surfaces(p);
    return [this.xs.slice().reverse().concat(this.xs.slice(1)), yu.slice().reverse().concat(yl.slice(1))];
  }
}

/** Fit a CST to an arbitrary seed. Returns [cst, params, maxFitError]. */
export function fitSeed(coords) {
  const [c, ile] = normalizeSeed(coords);
  const up = argsortX(c.slice(0, ile + 1).reverse());
  const lo = argsortX(c.slice(ile));
  const dzU = interp(1.0, up.map((p) => p[0]), up.map((p) => p[1]));
  const dzL = interp(1.0, lo.map((p) => p[0]), lo.map((p) => p[1]));
  let best = null;
  for (const order of CST_ORDERS) {
    const cst = new CST(order, dzU, dzL);
    const params = [];
    let err = 0.0;
    for (const [srf, dz] of [[up, dzU], [lo, dzL]]) {
      const sel = srf.filter((p) => p[0] > 1e-5 && p[0] < 1 - 1e-5);
      const xx = sel.map((p) => Math.min(1, Math.max(0, p[0])));
      const Bx = bern(xx, order);
      const A = xx.map((x, i) => Array.from(Bx[i], (b) => (Math.sqrt(x) * (1 - x)) * b));
      const rhs = sel.map((p, i) => p[1] - xx[i] * dz);
      const coef = lstsq(A, rhs);
      params.push(...coef);
      for (let i = 0; i < A.length; i++) {
        let s = 0;
        for (let j = 0; j < coef.length; j++) s += A[i][j] * coef[j];
        err = Math.max(err, Math.abs(s + xx[i] * dz - sel[i][1]));
      }
    }
    if (best === null || err < best[2]) best = [cst, params, err];
    if (err <= SEED_FIT_TOL) break;
  }
  return best;
}

// ── Target handling ─────────────────────────────────────────────────────────
export function cleanTarget(points, name) {
  if (!Array.isArray(points) || points.length < 3 || points.some((p) => !Array.isArray(p) || p.length !== 2)) {
    throw new ValueError(`${name} needs at least 3 [x, Cp] points`);
  }
  const arr = points.map((p) => [Number(p[0]), Number(p[1])]);
  if (arr.some((p) => p.some((v) => Number.isNaN(v)))) throw new ValueError(`could not convert string to float`);
  return argsortX(arr);
}

function trapezoid(y, x) {
  let s = 0;
  for (let i = 0; i < x.length - 1; i++) s += (x[i + 1] - x[i]) * (y[i + 1] + y[i]) / 2.0;
  return s;
}

export function targetClFromCurve(tu, tl, alphaDeg) {
  const x = linspace(0, 1, 2001);
  const tlx = tl.map((p) => p[0]), tly = tl.map((p) => p[1]), tux = tu.map((p) => p[0]), tuy = tu.map((p) => p[1]);
  const cn = trapezoid(x.map((xi) => interp(xi, tlx, tly) - interp(xi, tux, tuy)), x);
  return cn * Math.cos(alphaDeg * (Math.PI / 180));
}

export function targetWarnings(tu, tl) {
  const w = [];
  if (maxOf(tu.map((p) => p[1])) > MAX_CP + 1e-6 || maxOf(tl.map((p) => p[1])) > MAX_CP + 1e-6) {
    w.push("The target has Cp above 1 somewhere. Cp can't exceed 1 (stagnation) in "
      + "incompressible flow, so those points were capped at 1.");
  }
  const teGap = Math.abs(tu[tu.length - 1][1] - tl[tl.length - 1][1]);
  if (teGap > 0.1) {
    w.push(`Upper and lower target Cp differ by ${pyFixed(teGap, 2)} at the trailing edge. `
      + "Real flow leaves the trailing edge smoothly (equal pressure on both sides), "
      + "so the design can't match both there.");
  }
  return w;
}

// ── XFOIL viscous evaluation ────────────────────────────────────────────────
function parsePacc(text) {
  const rows = [];
  if (text == null) return rows;
  let started = false;
  for (const line of text.split(/\r?\n/)) {
    if (line.trim().startsWith("------")) { started = true; continue; }
    const parts = line.trim().split(/\s+/).filter(Boolean);
    if (started && parts.length >= 5) {
      const v = parts.slice(0, 5).map(pyFloat);
      if (v.every((x) => x !== null)) rows.push(v);
    }
  }
  return rows;
}

function readCpwr(text) {
  if (text == null) return null;
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    const parts = line.trim().split(/\s+/).filter(Boolean);
    if (parts.length < 2) continue;
    const v = parts.map(pyFloat);
    if (v.some((x) => x === null)) continue;
    rows.push([v[0], v[v.length - 1]]);
  }
  return rows.length >= 10 ? rows : null;
}

/** Viscous XFOIL on the given coordinates (PCOP, then PANE, then an alpha ramp). */
export async function xfoilViscous(runXfoil, x, y, reynolds, alpha, ncrit, tag, timeout = 60) {
  const geo = `geo_${tag}.dat`;
  const geoText = "DESIGN\n" + x.map((xi, i) => `${pyFixed(xi, 7)} ${pyFixed(y[i], 7)}\n`).join("");
  const attempts = [["PCOP", [`ALFA ${pyStr(alpha)}`]], ["PANE", [`ALFA ${pyStr(alpha)}`]]];
  if (x.length > 300) attempts.reverse();
  if (Math.abs(alpha) > 1.0) {
    const step = alpha > 0 ? 1.0 : -1.0;
    attempts.push(["PANE", [`ASEQ 0 ${pyStr(alpha - step)} ${pyStr(step)}`, `ALFA ${pyStr(alpha)}`]]);
  }
  for (let k = 0; k < attempts.length; k++) {
    const [pan, oper] = attempts[k];
    const pol = `pol_${tag}_${k}.dat`, cpf = `cp_${tag}_${k}.dat`;
    const script = ["PLOP", "G", "", `LOAD ${geo}`, pan, "OPER",
      `VISC ${Math.trunc(reynolds)}`, "ITER 200", "VPAR", `N ${pyStr(ncrit)}`, "",
      "PACC", pol, "", ...oper, "PACC", `CPWR ${cpf}`, "", "QUIT"];
    let res;
    try {
      res = await runXfoil(`${script.join("\n")}\n`, { [geo]: geoText }, [pol, cpf], timeout * 1000);
    } catch (e) {
      if (e instanceof XfoilTimeout) continue;
      throw e;
    }
    const rows = parsePacc(res.files[pol]).filter((r) => Math.abs(r[0] - alpha) < 1e-3);
    if (!rows.length || res.files[cpf] == null) continue;
    const cp = readCpwr(res.files[cpf]);
    if (cp === null) continue;
    if (!cp.every((r) => Number.isFinite(r[0]) && Number.isFinite(r[1])) || maxOf(cp.map((r) => Math.abs(r[1]))) > 20) continue;
    const ile = argminFirst(cp.map((r) => r[0]));
    const up = cp.slice(0, ile + 1).reverse(), lo = cp.slice(ile);
    const [, cl, cd, , cm] = rows[rows.length - 1];
    return { ok: true, CL: cl, CD: cd, CM: cm, upper: argsortX(up), lower: argsortX(lo), method: oper.length === 1 ? pan : "PANE+ramp" };
  }
  return { ok: false };
}

// ── The optimisation ────────────────────────────────────────────────────────
/**
 * The least-squares residual (Cp mismatch weighted by sqrt(panel length),
 * thickness penalties, light regularisation) built from plain data, so the
 * design worker and its panel workers compute exactly the same numbers.
 */
export function makeResiduals({ order, dzU, dzL, alpha, sqrtL, p0, minThickness, regularization }) {
  const cst = new CST(order, dzU, dzL);
  const tFloor = thicknessLimit(cst.xs);
  return (p, tgt) => {
    const [x, y] = cst.coords(p);
    const { cp } = panelCp(x, y, alpha);
    const out = [];
    for (let i = 0; i < cp.length; i++) out.push(sqrtL[i] * (tgt[i] - cp[i]));
    const [yu, yl] = cst.surfaces(p);
    const th = yu.map((v, i) => v - yl[i]);
    for (let i = 1; i < th.length - 1; i++) out.push(10.0 * Math.max(0.0, tFloor[i] - th[i]));
    if (minThickness > 0) out.push(100.0 * Math.max(0.0, minThickness - maxOf(th)));
    for (let i = 0; i < p.length; i++) out.push(regularization * (p[i] - p0[i]));
    return out;
  };
}

const panelSplit = () => N_SURF - 1;

function onPanels(xc, curves) {
  const nUp = panelSplit();
  const [u, l] = curves;
  const ux = u.map((p) => p[0]), uy = u.map((p) => p[1]), lx = l.map((p) => p[0]), ly = l.map((p) => p[1]);
  return xc.map((x, i) => (i < nUp ? interp(x, ux, uy) : interp(x, lx, ly)));
}

const thicknessLimit = (xs) => xs.map((x) => 0.002 * 4 * x * (1 - x));

function liftGapRegion(xc, L, err, nUp, width = 0.1) {
  let best = [0.0, "", 0.0];
  for (const [name, lo, hi, sign] of [["upper", 0, nUp, -1.0], ["lower", nUp, xc.length, 1.0]]) {
    // np.arange(0.0, 1.0, width)
    const count = Math.ceil((1.0 - 0.0) / width);
    for (let k = 0; k < count; k++) {
      const a = 0.0 + k * width;
      let contrib = 0;
      for (let i = lo; i < hi; i++) if (xc[i] >= a && xc[i] < a + width) contrib += sign * err[i] * L[i];
      if (Math.abs(contrib) > Math.abs(best[0])) best = [contrib, name, a];
    }
  }
  const [, name, a] = best;
  return `the ${name} surface between x/c = ${pyFixed(a, 1)} and ${pyFixed(a + width, 1)}`;
}

/**
 * Same inputs and result as inverse_design.run_inverse_design. minThickness is
 * a fraction of chord; progress(fraction, message) reports the real stage.
 * pool (optional): { setup(spec), evalMany(points, tgt) } spreads the
 * finite-difference Jacobian over other workers (see makeResiduals).
 */
export async function runInverseDesign(runXfoil, reynolds, alpha, targetCpUpper, targetCpLower, {
  seedCoords = null, ncrit = 9.0, minThickness = 0.0, nViscous = 6, maxSeconds = 90.0,
  regularization = 1e-3, progress = null, pool = null,
} = {}) {
  const tStart = now();
  const totalSteps = 4 + nViscous;
  const report = (done, message) => { if (progress) { try { progress(Math.min(1.0, done / totalSteps), message); } catch { /* ignore */ } } };

  report(0, "Fitting the seed shape");
  const warnings = [];
  const tu = cleanTarget(targetCpUpper, "target_cp_upper");
  const tl = cleanTarget(targetCpLower, "target_cp_lower");
  warnings.push(...targetWarnings(tu, tl));
  for (const p of tu) p[1] = Math.min(p[1], MAX_CP);
  for (const p of tl) p[1] = Math.min(p[1], MAX_CP);

  let seedName;
  if (seedCoords === null) { seedCoords = defaultSeed(); seedName = "NACA 0012 (default)"; } else seedName = "uploaded seed";
  const [cst, p0, fitErr] = fitSeed(seedCoords);
  if (fitErr > 5e-3) {
    warnings.push(`The seed airfoil could only be approximated to ${pyFixed(fitErr * 100, 2)}% chord by the `
      + "smooth shape functions used for design (sharp kinks or noisy points).");
  }

  const [x0, y0] = cst.coords(p0);
  const { xc: xc0 } = panelCp(x0, y0, alpha);
  const L = x0.slice(0, -1).map((xi, i) => Math.hypot(x0[i + 1] - xi, y0[i + 1] - y0[i]));
  const sqrtL = L.map(Math.sqrt);
  const targetPanels = onPanels(xc0, [tu, tl]);

  // Everything the residual needs, as plain data, so panel workers can rebuild it.
  const spec = { order: cst.n, dzU: cst.dzU, dzL: cst.dzL, alpha, sqrtL, p0, minThickness, regularization };
  const residuals = makeResiduals(spec);
  const lb = p0.map((v) => v - 0.5), ub = p0.map((v) => v + 0.5);
  const history = [];

  report(1, "Checking the seed airfoil in XFOIL");
  const seedEval = await xfoilViscous(runXfoil, x0, y0, reynolds, alpha, ncrit, "seed");

  if (pool) await pool.setup(spec);
  const solveInviscid = async (start, tgt) => (await leastSquaresTrf((p) => residuals(p, tgt), start, lb, ub,
    { xScale: 0.02, diffStep: 1e-4, maxNfev: 80, evalMany: pool ? (pts) => pool.evalMany(pts, tgt) : null })).x;

  const evaluate = async (p, tag) => {
    const [x, y] = cst.coords(p);
    const { xc, cp: cpInv } = panelCp(x, y, alpha);
    const visc = await xfoilViscous(runXfoil, x, y, reynolds, alpha, ncrit, tag);
    if (!visc.ok) return null;
    const cpVisc = onPanels(xc, [visc.upper, visc.lower]);
    const err = targetPanels.map((t, i) => t - cpVisc[i]);
    let num = 0, den = 0;
    for (let i = 0; i < L.length; i++) { num += L[i] * err[i] ** 2; den += L[i]; }
    return { rms: Math.sqrt(num / den), visc, cp_inv: cpInv, cp_visc: cpVisc, err, p };
  };

  report(2, "Matching the target pressure distribution");
  let p = await solveInviscid(p0.slice(), targetPanels);
  report(3, "Checking the first design in viscous XFOIL");
  let state = await evaluate(p, "it0");
  history.push({ iteration: 0, viscous_converged: state !== null, ...(state ? { viscous_rms: state.rms, CL: state.visc.CL } : {}) });
  let best = state ? { ...state, iteration: 0 } : { p, visc: null, rms: null, err: null, iteration: 0 };

  let it = 0;
  while (state !== null && it < nViscous) {
    if (now() - tStart > maxSeconds) {
      warnings.push("Stopped the viscous refinement early to stay within the time limit.");
      break;
    }
    it += 1;
    report(3 + it, `Viscous correction ${it} of up to ${nViscous}`);
    const tgtInv = targetPanels.map((t, i) => t - (state.cp_visc[i] - state.cp_inv[i]));
    const cand = await solveInviscid(state.p, tgtInv);
    let accepted = null, step = null;
    const steps = [1.0, 0.5, 0.25];
    for (let k = 0; k < steps.length; k++) {
      step = steps[k];
      const trial = await evaluate(state.p.map((v, i) => v + step * (cand[i] - v)), `it${it}_${k}`);
      if (trial !== null && trial.rms < state.rms * 0.995) { accepted = trial; break; }
    }
    if (accepted === null) break;
    state = accepted;
    history.push({ iteration: it, viscous_converged: true, viscous_rms: state.rms, CL: state.visc.CL, step });
    if (state.rms < best.rms) best = { ...state, iteration: it };
    if (state.rms < 0.005) break;
  }

  report(totalSteps, "Finishing");
  const pBest = best.p;
  const [x, y] = cst.coords(pBest);
  const { xc, cp: cpInvBest } = panelCp(x, y, alpha);
  const [yu, yl] = cst.surfaces(pBest);
  const th = yu.map((v, i) => v - yl[i]);
  const [yu0, yl0] = cst.surfaces(p0);
  const th0 = yu0.map((v, i) => v - yl0[i]);
  const visc = best.visc;
  const verified = visc !== null;

  const nUp = panelSplit();
  let perSurface = null;
  if (verified) {
    const e = best.err;
    const rmsOf = (lo, hi) => { let a = 0, b = 0; for (let i = lo; i < hi; i++) { a += L[i] * e[i] ** 2; b += L[i]; } return Math.sqrt(a / b); };
    const absE = e.map(Math.abs);
    perSurface = {
      upper_rms: rmsOf(0, nUp), lower_rms: rmsOf(nUp, L.length),
      max_abs_error: maxOf(absE), x_of_max_error: xc[argmaxFirst(absE)],
    };
    const targetCl = targetClFromCurve(tu, tl, alpha);
    if (Math.abs(targetCl) > 0.05 && Math.abs(visc.CL - targetCl) > 0.1 * Math.abs(targetCl)) {
      warnings.push(
        `The designed airfoil makes CL = ${pyFixed(visc.CL, 3)}, ${pyFixed(Math.abs(visc.CL - targetCl) / Math.abs(targetCl) * 100, 0)}% `
        + `${visc.CL < targetCl ? "below" : "above"} the ${pyFixed(targetCl, 3)} your curve implies. Most of `
        + `the lift difference comes from ${liftGapRegion(xc, L, best.err, nUp)}. Usually this means part of `
        + "the target can't happen in real viscous flow, most often a pressure recovery too steep for the "
        + "boundary layer, which then separates.");
    }
  } else {
    warnings.push("XFOIL's viscous analysis didn't converge on the designed shape, so the "
      + "result below is the inviscid design only (not viscous-verified).");
  }

  return {
    verification_succeeded: verified,
    seed_name: seedName,
    seed_fit_error: fitErr,
    target_cl: targetClFromCurve(tu, tl, alpha),
    coefficients: verified ? { CL: visc.CL, CD: visc.CD, CM: visc.CM } : null,
    inviscid_cl: pressureCl(x, y, cpInvBest, alpha),
    seed_coefficients: seedEval.ok ? { CL: seedEval.CL, CD: seedEval.CD, CM: seedEval.CM } : null,
    fit: { viscous_rms: best.rms, ...(perSurface || {}) },
    new_coords: x.map((xi, i) => [xi, y[i]]),
    seed_coords: x0.map((xi, i) => [xi, y0[i]]),
    max_thickness: maxOf(th), max_thickness_x: cst.xs[argmaxFirst(th)],
    seed_max_thickness: maxOf(th0),
    result_cp_upper: verified ? visc.upper : null,
    result_cp_lower: verified ? visc.lower : null,
    target_cp_upper: tu, target_cp_lower: tl,
    history,
    best_iteration: best.iteration,
    warnings,
    elapsed_seconds: now() - tStart,
  };
}

/** The seed's own Cp at the condition, sampled at the editor's points (inverse_design.seed_baseline). */
export async function seedBaseline(runXfoil, reynolds, alpha, seedCoords = null, ncrit = 9.0) {
  if (seedCoords === null) seedCoords = defaultSeed();
  const [c] = normalizeSeed(seedCoords);
  const xe = cosineX(EDITOR_POINTS);
  const visc = await xfoilViscous(runXfoil, c.map((p) => p[0]), c.map((p) => p[1]), reynolds, alpha, ncrit, "baseline");
  let up, lo, source, cl;
  if (visc.ok) {
    [up, lo, source, cl] = [visc.upper, visc.lower, "xfoil_viscous", visc.CL];
  } else {
    const xs = c.map((p) => p[0]), ys = c.map((p) => p[1]);
    const { xc, cp } = panelCp(xs, ys, alpha);
    const k = argminFirst(xc);
    up = argsortX(xc.slice(0, k + 1).map((v, i) => [v, cp[i]]).reverse());
    lo = argsortX(xc.slice(k).map((v, i) => [v, cp[k + i]]));
    source = "panel_inviscid";
    cl = pressureCl(xs, ys, cp, alpha);
  }
  const cu = xe.map((x) => interp(x, up.map((p) => p[0]), up.map((p) => p[1])));
  const cL = xe.map((x) => interp(x, lo.map((p) => p[0]), lo.map((p) => p[1])));
  const le = Math.max(cu[0], cL[0]);
  const te = 0.5 * (cu[cu.length - 1] + cL[cL.length - 1]);
  cu[0] = cL[0] = Math.min(le, MAX_CP);
  cu[cu.length - 1] = cL[cL.length - 1] = te;
  return {
    x: xe.map((v) => pyRound(v, 4)), upper: cu.map((v) => pyRound(v, 4)), lower: cL.map((v) => pyRound(v, 4)),
    source, CL: cl, seed_coords: c,
  };
}
