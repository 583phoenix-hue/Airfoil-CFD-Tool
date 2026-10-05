// Control (aileron) reversal on the torsion-only typical section.
// JavaScript port of the backend's control_reversal.py; keep the two in step.

import { interp, pchip, pyFixed, pyRound } from "./numerics.js";
import {
  XfoilPolarError, divergenceFromPolar, runPolar, speedGrid, traceEquilibriumBranch,
} from "./divergence.js";

export const FLAP_TEST_DEFLECTION_DEG = 2.0;

/** Thin-airfoil (dCl/ddelta, dCm_c4/ddelta) per radian, scaled by the real lift-curve slope. */
export function thinFlapDerivatives(flapChordFraction, a0RealPerRad) {
  const thetaF = Math.acos(2 * flapChordFraction - 1);
  const dclIdeal = 2 * (Math.PI - thetaF + Math.sin(thetaF));
  const dcmIdeal = 0.5 * Math.sin(thetaF) * (Math.cos(thetaF) - 1);
  const scale = a0RealPerRad / (2 * Math.PI);
  return [dclIdeal * scale, dcmIdeal * scale];
}

export class FlapDerivatives {
  constructor(alpha, clD, cmD, source) {
    this.source = source;
    this.alpha = alpha;
    this.alphaMin = alpha.length ? alpha[0] : -1e9;
    this.alphaMax = alpha.length ? alpha[alpha.length - 1] : 1e9;
    if (alpha.length >= 2) {
      this._cl = pchip(alpha, clD); this._cm = pchip(alpha, cmD); this._const = null;
    } else {
      this._const = [clD[0], cmD[0]];
    }
  }

  static constant(clD, cmD, source) {
    const obj = new FlapDerivatives([0.0], [clD], [cmD], source);
    obj.alphaMin = -1e9; obj.alphaMax = 1e9;
    return obj;
  }

  contains(a) { return this.alphaMin <= a && a <= this.alphaMax; }

  at(a) {
    if (this._const) {
      if (Array.isArray(a)) return [a.map(() => this._const[0]), a.map(() => this._const[1])];
      return [this._const[0], this._const[1]];
    }
    return [this._cl.at(a), this._cm.at(a)];
  }
}

export async function measureFlapDerivatives(runXfoil, seed, reynolds, ncrit, flapChordFraction, anchorAlpha,
  deltaDeg = FLAP_TEST_DEFLECTION_DEG) {
  // The two flap polars are independent, so they run at the same time
  // (separate XFOIL workers); errors are reported in the same order as the
  // sequential Python version (plus first).
  const [pr, mr] = await Promise.allSettled([
    runPolar(runXfoil, seed, reynolds, ncrit, { anchorAlpha, flap: [flapChordFraction, deltaDeg], tag: "flap_plus" }),
    runPolar(runXfoil, seed, reynolds, ncrit, { anchorAlpha, flap: [flapChordFraction, -deltaDeg], tag: "flap_minus" }),
  ]);
  if (pr.status === "rejected") throw pr.reason;
  if (mr.status === "rejected") throw mr.reason;
  const plus = pr.value, minus = mr.value;
  const ps = new Set(plus.alpha.map((a) => pyRound(a, 4)));
  const common = [...new Set(minus.alpha.map((a) => pyRound(a, 4)))].filter((a) => ps.has(a)).sort((x, y) => x - y);
  if (common.length < 3) throw new XfoilPolarError("Flap polars share too few converged angles");
  const dRad = (2 * deltaDeg) * (Math.PI / 180);
  const a = [], clD = [], cmD = [];
  for (const x of common) {
    const cl = (plus.cl(x) - minus.cl(x)) / dRad;
    const cm = (plus.cm(x) - minus.cm(x)) / dRad;
    if (Number.isFinite(cl) && Number.isFinite(cm)) { a.push(x); clD.push(cl); cmD.push(cm); }
  }
  if (a.length < 3) throw new XfoilPolarError("Flap polars share too few converged angles");
  return new FlapDerivatives(a, clD, cmD, "xfoil");
}

const firstFalse = (arr) => { const i = arr.indexOf(false); return i < 0 ? arr.length : i; };

export function reversalFromPolar(polar, flap, alphaRoot, kAlpha, xEa, chord, span, rho, flapChordFraction,
  vStart = 2.0, vStep = 2.0, vMax = 150.0) {
  const S = chord * span;
  const warnings = [];
  const qMax = 0.5 * rho * vMax ** 2;

  const branch = traceEquilibriumBranch(polar, alphaRoot, kAlpha, xEa, chord, span);
  const div = divergenceFromPolar(polar, alphaRoot, kAlpha, xEa, chord, span, rho, vStart, vStep, vMax);
  const a0Root = polar.aeroParams(alphaRoot);
  const [thinClD, thinCmD] = thinFlapDerivatives(flapChordFraction, a0Root.a0_per_rad);

  // Effectiveness along the dense branch
  const inFlap = branch.alpha_deg.map((a) => a >= flap.alphaMin && a <= flap.alphaMax);
  const nOk = firstFalse(inFlap);
  const th = branch.theta_deg.slice(0, nOk), al = branch.alpha_deg.slice(0, nOk);
  const q = branch.q.slice(0, nOk), kEff = branch.k_eff.slice(0, nOk);

  const [clD, cmD] = flap.at(al);
  const eta = al.map((a, i) => {
    const clA = polar._cl.deriv(a) * 180.0 / Math.PI;
    const cmEaD = cmD[i] + clD[i] * (xEa - 0.25);
    const dthetaDdelta = q[i] * S * chord * cmEaD / kEff[i];
    const dclTotal = clD[i] + clA * dthetaDdelta;
    return dclTotal / clD[i];
  });

  const isDiv = div.stopped_reason === "divergence_found" || div.stopped_reason === "stall_limited_divergence";
  const vDiv = isDiv ? div.v_div : null;
  const qDiv = vDiv !== null ? div.q_div : null;
  const usable = eta.map((e, i) => Number.isFinite(e) && kEff[i] > 0 && q[i] <= qMax && (qDiv === null || q[i] <= qDiv));
  const last = firstFalse(usable);

  let qRev = null, vRev = null, alphaRev = null, stoppedReason;
  const signs = eta.slice(0, last).map((e) => (e > 0 ? 1 : e < 0 ? -1 : e === 0 ? 0 : NaN));
  let cross = -1;
  for (let i = 0; i < signs.length - 1; i++) if (signs[i] > 0 && signs[i + 1] <= 0) { cross = i; break; }
  if (cross >= 0) {
    const i = cross;
    const f = eta[i] / (eta[i] - eta[i + 1]);
    qRev = q[i] + f * (q[i + 1] - q[i]);
    alphaRev = al[i] + f * (al[i + 1] - al[i]);
    vRev = Math.sqrt(2 * qRev / rho);
    stoppedReason = "reversal_found";
  } else if (vDiv !== null) {
    stoppedReason = "divergence_before_reversal";
  } else if (nOk < branch.alpha_deg.length && (q.length === 0 || q[q.length - 1] < qMax)) {
    stoppedReason = "flap_data_range_exceeded";
    const vEdge = q.length ? Math.sqrt(2 * q[q.length - 1] / rho) : 0.0;
    warnings.push(
      `Above ${pyFixed(vEdge, 1)} m/s the twisted section leaves the angle range where the `
      + `XFOIL flap polars converged (${pyFixed(flap.alphaMin, 1)} to ${pyFixed(flap.alphaMax, 1)} deg).`);
  } else if (q.length && q[q.length - 1] < qMax && div.stopped_reason === "polar_range_exceeded") {
    stoppedReason = "polar_range_exceeded";
    warnings.push(...div.warnings.filter((w) => w.includes("could not be assessed")));
  } else {
    stoppedReason = "no_reversal_within_range";
  }

  // Linear theory at the root condition
  let clD0, cmD0;
  if (flap.contains(alphaRoot)) [clD0, cmD0] = flap.at(alphaRoot);
  else [clD0, cmD0] = [thinClD, thinCmD];
  const xAc = a0Root.x_ac_over_c;
  const cmAcD = cmD0 + clD0 * (xAc - 0.25);
  let linQ = null, linV = null;
  if (cmAcD < 0 && a0Root.a0_per_rad > 0) {
    linQ = -kAlpha * clD0 / (S * chord * a0Root.a0_per_rad * cmAcD);
    linV = Math.sqrt(2 * linQ / rho);
  } else {
    warnings.push("The flap produces no nose-down moment about the aerodynamic centre "
      + "here, so classical control reversal cannot occur.");
  }

  if (vRev !== null && linV) {
    const gap = Math.abs(vRev - linV) / linV;
    if (gap > 0.15) {
      warnings.push(
        `Nonlinear reversal speed (${pyFixed(vRev, 1)} m/s) differs from the linear estimate `
        + `(${pyFixed(linV, 1)} m/s) by ${pyFixed(gap * 100, 0)}%, because the lift, moment and flap `
        + `curves change over the twist range involved.`);
    }
  }
  if (stoppedReason === "divergence_before_reversal") {
    warnings.push(
      `The section diverges at ${pyFixed(vDiv, 1)} m/s before the control reverses, so the `
      + `divergence speed is the limiting one.`);
  }

  // History on the user's speed grid
  const history = [];
  const qL = q.slice(0, last), etaL = eta.slice(0, last), thL = th.slice(0, last), clDL = clD.slice(0, last);
  for (const v of speedGrid(vStart, vStep, vMax)) {
    const qv = 0.5 * rho * v ** 2;
    if (last === 0 || qv > q[last - 1]) break;
    let idxEta, idxTh;
    if (qv < q[0]) { idxEta = eta[0]; idxTh = th[0] * qv / q[0]; }
    else { idxEta = interp(qv, qL, etaL); idxTh = interp(qv, qL, thL); }
    history.push({
      v, q: qv, alpha_elastic_deg: idxTh, effectiveness: idxEta,
      dcl_ddelta_aeroelastic: idxEta * interp(qv, qL, clDL),
    });
  }
  if (vRev !== null) {
    history.push({ v: vRev, q: qRev, alpha_elastic_deg: alphaRev - alphaRoot, effectiveness: 0.0, dcl_ddelta_aeroelastic: 0.0 });
    history.sort((p, r) => p.v - r.v);
  }

  return {
    v_reversal: vRev, q_reversal: qRev,
    stopped_reason: stoppedReason,
    v_div: vDiv,
    a0_per_rad: a0Root.a0_per_rad,
    x_ac_over_c: xAc,
    flap_derivatives: {
      source: flap.source,
      cl_delta_per_rad: clD0,
      cm_c4_delta_per_rad: cmD0,
      thin_airfoil_cl_delta_per_rad: thinClD,
      thin_airfoil_cm_c4_delta_per_rad: thinCmD,
    },
    linear: { q_reversal: linQ, v_reversal: linV, cm_ac_delta_per_rad: cmAcD },
    history, warnings,
  };
}

export async function analyzeReversal(runXfoil, seed, reynolds, ncrit, alphaRoot, kAlpha, xEa, chord, span, rho,
  flapChordFraction, vStart = 2.0, vStep = 2.0, vMax = 150.0, flapSource = "xfoil") {
  // Base and flap polars run at the same time; the base polar's errors come first.
  const flapPromise = flapSource === "xfoil"
    ? measureFlapDerivatives(runXfoil, seed, reynolds, ncrit, flapChordFraction, alphaRoot) : null;
  if (flapPromise) flapPromise.catch(() => {}); // handled below
  const polar = await runPolar(runXfoil, seed, reynolds, ncrit, { anchorAlpha: alphaRoot });
  const a0 = polar.aeroParams(alphaRoot).a0_per_rad;
  let fallbackNote = null, flap;
  if (flapSource === "xfoil") {
    try {
      flap = await flapPromise;
      if (!flap.contains(alphaRoot)) throw new XfoilPolarError("flap polars don't cover the root angle");
    } catch (e) {
      if (!(e instanceof XfoilPolarError)) throw e;
      fallbackNote = `XFOIL flap polars didn't converge well enough (${e.message}); `
        + "used thin-airfoil flap derivatives instead.";
      flap = FlapDerivatives.constant(...thinFlapDerivatives(flapChordFraction, a0), "thin_airfoil");
    }
  } else {
    flap = FlapDerivatives.constant(...thinFlapDerivatives(flapChordFraction, a0), "thin_airfoil");
  }
  const result = reversalFromPolar(polar, flap, alphaRoot, kAlpha, xEa, chord, span, rho,
    flapChordFraction, vStart, vStep, vMax);
  if (fallbackNote) result.warnings.unshift(fallbackNote);
  result.polar = polar.toDict();
  return result;
}
