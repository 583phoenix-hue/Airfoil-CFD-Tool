// Static torsional divergence + the shared XFOIL polar layer.
// JavaScript port of the backend's static_divergence.py (same physics, same
// steps, same messages); see that file for the full derivation. Keep the two
// in step.
//
// `runXfoil(script, files, readNames, timeoutMs)` is injected (the browser
// passes the WebAssembly worker pool; tests can pass a Node runner).

import { pyFloat } from "../airfoilParser.js";
import { pyStr, XfoilTimeout } from "../xfoil/analysis.js";
import { interp, linspace, lsqSlope, pchip, pyFixed, pyRound } from "./numerics.js";

export const DEFAULT_ALPHA_MIN = -10.0;
export const DEFAULT_ALPHA_MAX = 20.0;
export const DEFAULT_ALPHA_STEP = 0.5;
export const RUNAWAY_STIFFNESS_RATIO = 0.15;

export class XfoilPolarError extends Error {}

const DEG = 180.0 / Math.PI;

// ── XFOIL polar layer ───────────────────────────────────────────────────────
export function parsePacc(text) {
  const rows = [];
  if (text == null) return rows;
  let started = false;
  for (const line of text.split(/\r?\n/)) {
    if (!started) {
      if (line.trim().startsWith("------")) started = true;
      continue;
    }
    const parts = line.trim().split(/\s+/).filter(Boolean);
    if (parts.length < 5) continue;
    const v = parts.slice(0, 5).map(pyFloat);
    if (v.some((x) => x === null)) continue;
    rows.push([v[0], v[1], v[2], v[4]]); // alpha, cl, cd, cm
  }
  return rows;
}

function cleanRows(rows, alphaStep) {
  const byAlpha = new Map();
  for (const r of rows) byAlpha.set(pyRound(r[0], 4), r);
  const pts = [...byAlpha.keys()].sort((a, b) => a - b).map((k) => byAlpha.get(k));
  if (pts.length < 3) return pts;
  const keep = pts.map(() => true);
  for (let i = 1; i < pts.length - 1; i++) {
    const [a0, cl0] = pts[i - 1], [a1, cl1] = pts[i], [a2, cl2] = pts[i + 1];
    if (a2 - a0 > 3 * alphaStep) continue;
    const expected = cl0 + (cl2 - cl0) * (a1 - a0) / (a2 - a0);
    if (Math.abs(cl1 - expected) > 0.2 && Math.abs(cl2 - cl0) < 0.2) keep[i] = false;
  }
  return pts.filter((_, i) => keep[i]);
}

const argmaxFirst = (arr) => { let k = 0; for (let i = 1; i < arr.length; i++) if (arr[i] > arr[k]) k = i; return k; };
const argminFirst = (arr) => { let k = 0; for (let i = 1; i < arr.length; i++) if (arr[i] < arr[k]) k = i; return k; };

/** Converged XFOIL polar with monotone (PCHIP) interpolation. */
export class Polar {
  constructor(alpha, cl, cm, cd, label = "base") {
    this.alpha = alpha; this.clData = cl; this.cmData = cm; this.cdData = cd; this.label = label;
    this.alphaMin = alpha[0]; this.alphaMax = alpha[alpha.length - 1];
    this._cl = pchip(alpha, cl);
    this._cm = pchip(alpha, cm);
    const iMax = argmaxFirst(cl), iMin = argminFirst(cl);
    this.stallAlphaPos = iMax < alpha.length - 1 ? alpha[iMax] : null;
    this.stallAlphaNeg = iMin > 0 ? alpha[iMin] : null;
  }

  contains(a) { return this.alphaMin <= a && a <= this.alphaMax; }
  cl(a) { return this._cl.at(a); }
  cm(a) { return this._cm.at(a); }

  /** Least-squares dCl/dalpha, dCm/dalpha (per degree) within +/- half_window deg. */
  localSlopes(a, halfWindow = 1.0) {
    let idx = [];
    this.alpha.forEach((x, i) => { if (Math.abs(x - a) <= halfWindow + 1e-9) idx.push(i); });
    if (idx.length < 3) {
      idx = this.alpha.map((x, i) => [Math.abs(x - a), i]).sort((p, q) => p[0] - q[0]).slice(0, 3)
        .map((p) => p[1]).sort((p, q) => p - q);
    }
    const xs = idx.map((i) => this.alpha[i]);
    return [lsqSlope(xs, idx.map((i) => this.clData[i])), lsqSlope(xs, idx.map((i) => this.cmData[i]))];
  }

  aeroParams(a) {
    const [dcl, dcm] = this.localSlopes(a);
    const a0 = dcl * 180.0 / Math.PI;
    const xAc = 0.25 - (dcl !== 0 ? dcm / dcl : 0.0);
    return { a0_per_rad: a0, x_ac_over_c: xAc };
  }

  toDict() {
    return {
      alpha: this.alpha, cl: this.clData, cm: this.cmData, cd: this.cdData,
      stall_alpha_pos: this.stallAlphaPos, stall_alpha_neg: this.stallAlphaNeg,
    };
  }
}

const loadLines = (seedName) => (seedName ? [`LOAD ${seedName}`] : ["NACA 0012"]);

/**
 * One viscous XFOIL polar swept outward from anchorAlpha (static_divergence.run_polar).
 * seed: null (NACA 0012) or { name, text } for an uploaded, repaired airfoil.
 */
export async function runPolar(runXfoil, seed, reynolds, ncrit, {
  alphaMin = DEFAULT_ALPHA_MIN, alphaMax = DEFAULT_ALPHA_MAX, alphaStep = DEFAULT_ALPHA_STEP,
  anchorAlpha = 0.0, flap = null, tag = "base", timeout = 180,
} = {}) {
  const polarName = `polar_${tag}.txt`;
  const anchor = Math.max(alphaMin, Math.min(alphaMax, pyRound(anchorAlpha / alphaStep) * alphaStep));

  const lines = ["PLOP", "G", "", ...loadLines(seed && seed.name)];
  if (flap) {
    const [frac, delta] = flap;
    lines.push("GDES", "FLAP", (1.0 - frac).toFixed(4), "999", "0.5", delta.toFixed(4), "EXEC", "");
  }
  lines.push("PANE", "OPER", `VISC ${Math.trunc(reynolds)}`, "ITER 150", "VPAR", `N ${pyStr(ncrit)}`, "",
    "PACC", polarName, "");
  if (anchor < alphaMax) lines.push(`ASEQ ${pyStr(anchor)} ${pyStr(alphaMax)} ${pyStr(alphaStep)}`);
  else lines.push(`ALFA ${pyStr(anchor)}`);
  if (anchor > alphaMin) lines.push("INIT", `ASEQ ${pyStr(anchor - alphaStep)} ${pyStr(alphaMin)} ${pyStr(-alphaStep)}`);
  lines.push("PACC", "", "QUIT");

  const files = seed ? { [seed.name]: seed.text } : {};
  let res;
  try {
    res = await runXfoil(`${lines.join("\n")}\n`, files, [polarName], timeout * 1000);
  } catch (e) {
    if (e instanceof XfoilTimeout) throw new XfoilPolarError(`XFOIL timed out after ${timeout}s`);
    throw e;
  }
  const stdout = res.stdout || "";
  let rows = cleanRows(parsePacc(res.files[polarName]), alphaStep);

  // Keep only the contiguous block around the anchor
  if (rows.length) {
    const alphas = rows.map((r) => r[0]);
    const i0 = argminFirst(alphas.map((a) => Math.abs(a - anchor)));
    const gap = 3.5 * alphaStep;
    let lo = i0, hi = i0;
    while (lo > 0 && alphas[lo] - alphas[lo - 1] <= gap) lo--;
    while (hi < rows.length - 1 && alphas[hi + 1] - alphas[hi] <= gap) hi++;
    rows = rows.slice(lo, hi + 1);
  }
  if (rows.length < 5) {
    const tail = stdout ? stdout.slice(-400) : "";
    throw new XfoilPolarError(
      `XFOIL converged at only ${rows.length} angles for the ${tag} polar `
      + `(Re=${pyFixed(reynolds, 0)}). Try a different Reynolds number or airfoil. `
      + `Last XFOIL output: ${tail}`);
  }
  return new Polar(rows.map((r) => r[0]), rows.map((r) => r[1]), rows.map((r) => r[3]), rows.map((r) => r[2]), tag);
}

// ── Equilibrium branch ──────────────────────────────────────────────────────
export function cmEaFunctions(polar, xEa) {
  const arm = xEa - 0.25;
  const cmEa = (a) => polar._cm.at(a) + polar._cl.at(a) * arm;
  const dcmEaRad = (a) => (polar._cm.deriv(a) + polar._cl.deriv(a) * arm) * 180.0 / Math.PI;
  return { cmEa, dcmEaRad };
}

export function traceEquilibriumBranch(polar, alphaRoot, kAlpha, xEa, chord, span, dthetaDeg = 0.01) {
  if (!polar.contains(alphaRoot)) {
    throw new XfoilPolarError(
      `Root angle ${pyStr(alphaRoot)} deg is outside the converged XFOIL polar `
      + `range [${pyFixed(polar.alphaMin, 1)}, ${pyFixed(polar.alphaMax, 1)}] deg.`);
  }
  const S = chord * span;
  const { cmEa, dcmEaRad } = cmEaFunctions(polar, xEa);
  const cm0 = cmEa(alphaRoot);
  let direction;
  if (Math.abs(cm0) > 1e-7) direction = cm0 > 0 ? 1.0 : -1.0;
  else direction = dcmEaRad(alphaRoot) >= 0 ? 1.0 : -1.0;

  const room = direction > 0 ? polar.alphaMax - alphaRoot : alphaRoot - polar.alphaMin;
  const n = Math.max(Math.trunc(room / dthetaDeg), 2);
  let theta = linspace(dthetaDeg * 0.1, room, n).map((t) => direction * t);
  let alpha = theta.map((t) => alphaRoot + t);
  let q = [], kEff = [];
  for (let i = 0; i < n; i++) {
    const qi = (kAlpha * (theta[i] * (Math.PI / 180))) / ((S * chord) * cmEa(alpha[i]));
    q.push(qi);
    kEff.push(kAlpha - qi * S * chord * dcmEaRad(alpha[i]));
  }
  // valid while q is finite and positive
  let end = q.length, saturates = false;
  for (let i = 0; i < q.length; i++) if (!Number.isFinite(q[i]) || q[i] <= 0) { end = i; saturates = true; break; }
  theta = theta.slice(0, end); alpha = alpha.slice(0, end); q = q.slice(0, end); kEff = kEff.slice(0, end);

  let foldIndex = null;
  for (let i = 0; i < q.length - 1; i++) if (q[i + 1] - q[i] <= 0) { foldIndex = i; break; }
  if (foldIndex !== null) {
    const cut = foldIndex + 1;
    theta = theta.slice(0, cut); alpha = alpha.slice(0, cut); q = q.slice(0, cut); kEff = kEff.slice(0, cut);
  }
  return {
    theta_deg: theta, alpha_deg: alpha, q, k_eff: kEff, direction,
    folded: foldIndex !== null,
    saturates: saturates && foldIndex === null,
    hit_polar_edge: foldIndex === null && !saturates,
  };
}

export function interpOnBranch(branch, qTarget, key) {
  const q = branch.q;
  if (q.length === 0 || qTarget > q[q.length - 1]) return null;
  if (qTarget <= q[0]) return key === "theta_deg" ? branch[key][0] * qTarget / q[0] : branch[key][0];
  return interp(qTarget, q, branch[key]);
}

export function speedGrid(vStart, vStep, vMax) {
  vStart = Math.max(vStart, 0.1);
  vStep = Math.max(vStep, 0.01);
  const n = Math.floor((vMax - vStart) / vStep + 1e-9) + 1;
  const grid = [];
  for (let i = 0; i < Math.max(n, 1); i++) grid.push(vStart + i * vStep);
  if (grid[grid.length - 1] < vMax - 1e-9) grid.push(vMax);
  return grid;
}

export function linearDivergence(polar, alphaRoot, kAlpha, xEa, chord, span, rho) {
  const p = polar.aeroParams(alphaRoot);
  const e = xEa - p.x_ac_over_c;
  const out = { a0_per_rad: p.a0_per_rad, x_ac_over_c: p.x_ac_over_c, e_over_c: e, q_div: null, v_div: null };
  if (e > 0 && p.a0_per_rad > 0) {
    const q = kAlpha / (chord * span * chord * e * p.a0_per_rad);
    out.q_div = q;
    out.v_div = Math.sqrt(2 * q / rho);
  }
  return out;
}

// ── Divergence analysis ─────────────────────────────────────────────────────
export function divergenceFromPolar(polar, alphaRoot, kAlpha, xEa, chord, span, rho,
  vStart = 5.0, vStep = 2.0, vMax = 150.0) {
  const warnings = [];
  const linear = linearDivergence(polar, alphaRoot, kAlpha, xEa, chord, span, rho);
  const branch = traceEquilibriumBranch(polar, alphaRoot, kAlpha, xEa, chord, span);
  const qMax = 0.5 * rho * vMax ** 2;

  if (linear.e_over_c <= 0) {
    warnings.push(
      `The elastic axis (${pyFixed(xEa * 100, 1)}% chord) is at or ahead of the `
      + `aerodynamic centre (${pyFixed(linear.x_ac_over_c * 100, 1)}% chord), so lift twists `
      + `the section nose-down and torsional divergence cannot occur.`);
  }

  let qDiv = null, vDiv = null, thetaDiv = null, alphaDiv = null;
  const last = branch.q.length - 1;
  if (branch.folded) {
    qDiv = branch.q[last]; thetaDiv = branch.theta_deg[last]; alphaDiv = branch.alpha_deg[last];
    vDiv = Math.sqrt(2 * qDiv / rho);
  }

  // Minimum effective stiffness within the swept range
  const within = branch.q.map((q) => q <= qMax);
  const wIdx = within.map((w, i) => (w ? i : -1)).filter((i) => i >= 0);
  let kMinRatio = null, vKMin = null, iMin = null;
  if (wIdx.length) {
    const ratios = wIdx.map((i) => branch.k_eff[i] / kAlpha);
    iMin = argminFirst(ratios);
    kMinRatio = ratios[iMin];
    vKMin = Math.sqrt(2 * branch.q[wIdx[iMin]] / rho);
  }

  let stoppedReason;
  if (qDiv !== null && qDiv <= qMax) {
    stoppedReason = "divergence_found";
  } else if (kMinRatio !== null && kMinRatio < RUNAWAY_STIFFNESS_RATIO && iMin < wIdx.length - 1) {
    stoppedReason = "stall_limited_divergence";
    const j = wIdx[iMin];
    qDiv = branch.q[j]; thetaDiv = branch.theta_deg[j]; alphaDiv = branch.alpha_deg[j];
    vDiv = vKMin;
    const thBefore = interpOnBranch(branch, 0.5 * rho * (0.93 * vDiv) ** 2, "theta_deg");
    const thAfter = interpOnBranch(branch, Math.min(0.5 * rho * (1.07 * vDiv) ** 2, branch.q[last]), "theta_deg");
    warnings.push(
      `No strict mathematical divergence: the effective torsional stiffness `
      + `falls to ${pyFixed(kMinRatio * 100, 0)}% of the structural value at ${pyFixed(vDiv, 1)} m/s, `
      + `where the twist runs away (about ${pyFixed(thBefore, 1)} to ${pyFixed(thAfter, 1)} deg `
      + `between ${pyFixed(0.93 * vDiv, 0)} and ${pyFixed(1.07 * vDiv, 0)} m/s) until the airfoil's `
      + `lift and moment curves flatten out further along (stall, or laminar-bubble `
      + `effects in the XFOIL data) and stiffen it again. A real wing would not `
      + `survive that, so this is reported as the divergence speed.`);
  } else if (qDiv !== null) {
    stoppedReason = "no_divergence_in_range";
    qDiv = vDiv = thetaDiv = alphaDiv = null;
  } else if (branch.saturates) {
    stoppedReason = "no_divergence_possible";
  } else {
    const qEdge = branch.q.length ? branch.q[last] : 0.0;
    if (qEdge >= qMax) {
      stoppedReason = "no_divergence_in_range";
    } else {
      stoppedReason = "polar_range_exceeded";
      const vEdge = Math.sqrt(2 * qEdge / rho);
      warnings.push(
        `Above ${pyFixed(vEdge, 1)} m/s the equilibrium twist carries the section past `
        + `the angles XFOIL could converge (${pyFixed(polar.alphaMin, 1)} to `
        + `${pyFixed(polar.alphaMax, 1)} deg), so higher speeds could not be assessed.`);
    }
  }

  const history = [];
  for (const v of speedGrid(vStart, vStep, vMax)) {
    const q = 0.5 * rho * v ** 2;
    const th = interpOnBranch(branch, q, "theta_deg");
    if (th === null) break;
    const a = alphaRoot + th;
    const kEff = interpOnBranch(branch, q, "k_eff");
    const cl = polar.cl(a);
    history.push({ v, q, alpha_elastic_deg: th, alpha_total_deg: a, cl, k_eff: kEff, lift_per_span: q * chord * cl });
  }
  if (vDiv !== null && history.every((h) => Math.abs(h.v - vDiv) > 1e-6)) {
    const a = alphaDiv;
    const kAt = stoppedReason === "divergence_found" ? 0.0 : interpOnBranch(branch, qDiv, "k_eff");
    const cl = polar.cl(a);
    history.push({ v: vDiv, q: qDiv, alpha_elastic_deg: thetaDiv, alpha_total_deg: a, cl, k_eff: kAt,
      lift_per_span: qDiv * chord * cl });
    history.sort((p, r) => p.v - r.v);
  }

  // Stall along the loaded path
  const stall = branch.direction > 0 ? polar.stallAlphaPos : polar.stallAlphaNeg;
  if (stall !== null && history.length) {
    for (const h of history) {
      const past = branch.direction > 0 ? h.alpha_total_deg >= stall : h.alpha_total_deg <= stall;
      if (past) {
        warnings.push(
          `The twisted section reaches stall (about ${pyFixed(stall, 1)} deg) at `
          + `${pyFixed(h.v, 1)} m/s. Beyond that the result relies on post-stall `
          + `XFOIL data, which is much less reliable.`);
        break;
      }
    }
  }

  if ((stoppedReason === "divergence_found" || stoppedReason === "stall_limited_divergence") && linear.v_div) {
    const gap = Math.abs(vDiv - linear.v_div) / linear.v_div;
    if (gap > 0.15) {
      warnings.push(
        `Nonlinear divergence (${pyFixed(vDiv, 1)} m/s) differs from the linear `
        + `estimate (${pyFixed(linear.v_div, 1)} m/s) by ${pyFixed(gap * 100, 0)}%: the lift and `
        + `moment curves aren't straight over the twist range involved, so the `
        + `nonlinear value is the one to trust.`);
    }
  }

  return {
    v_div: vDiv, q_div: qDiv,
    alpha_elastic_at_div_deg: thetaDiv, alpha_total_at_div_deg: alphaDiv,
    stopped_reason: stoppedReason,
    min_stiffness_ratio: kMinRatio,
    v_at_min_stiffness: vKMin,
    linear, history, warnings,
  };
}

export async function analyzeDivergence(runXfoil, seed, reynolds, ncrit, alphaRoot, kAlpha, xEa, chord, span, rho,
  vStart = 5.0, vStep = 2.0, vMax = 150.0) {
  const polar = await runPolar(runXfoil, seed, reynolds, ncrit, { anchorAlpha: alphaRoot });
  const result = divergenceFromPolar(polar, alphaRoot, kAlpha, xEa, chord, span, rho, vStart, vStep, vMax);
  result.polar = polar.toDict();
  return result;
}

export { DEG };
