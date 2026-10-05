// Bounded nonlinear least squares: a port of SciPy's least_squares with
// method="trf", tr_solver="exact", loss="linear" and a '2-point' finite-
// difference Jacobian (scipy/optimize/_lsq/trf.py trf_bounds, common.py and
// _numdiff.py), which is what inverse_design.py calls.

import { EPS, dot, norm, normInf, svd } from "./linalg.js";

const inBounds = (x, lb, ub) => x.every((v, i) => v >= lb[i] && v <= ub[i]);

function findActive(x, lb, ub, rtol) {
  return x.map((xi, i) => {
    if (rtol === 0) return xi <= lb[i] ? -1 : xi >= ub[i] ? 1 : 0;
    const ld = xi - lb[i], ud = ub[i] - xi;
    const lt = rtol * Math.max(1, Math.abs(lb[i])), ut = rtol * Math.max(1, Math.abs(ub[i]));
    let a = 0;
    if (Number.isFinite(lb[i]) && ld <= Math.min(ud, lt)) a = -1;
    if (Number.isFinite(ub[i]) && ud <= Math.min(ld, ut)) a = 1;
    return a;
  });
}

function nextafter(x, toward) {
  if (x === toward || Number.isNaN(x) || Number.isNaN(toward)) return x;
  if (x === 0) return toward > 0 ? 5e-324 : -5e-324;
  const buf = new Float64Array([x]), bits = new BigInt64Array(buf.buffer);
  if ((toward > x) === (x > 0)) bits[0] += 1n; else bits[0] -= 1n;
  return buf[0];
}

function makeStrictlyFeasible(x, lb, ub, rstep = 1e-10) {
  const active = findActive(x, lb, ub, rstep);
  const out = x.slice();
  for (let i = 0; i < x.length; i++) {
    if (active[i] === -1) out[i] = rstep === 0 ? nextafter(lb[i], ub[i]) : lb[i] + rstep * Math.max(1, Math.abs(lb[i]));
    else if (active[i] === 1) out[i] = rstep === 0 ? nextafter(ub[i], lb[i]) : ub[i] - rstep * Math.max(1, Math.abs(ub[i]));
    if (out[i] < lb[i] || out[i] > ub[i]) out[i] = 0.5 * (lb[i] + ub[i]);
  }
  return out;
}

function clScalingVector(x, g, lb, ub) {
  const v = x.map(() => 1), dv = x.map(() => 0);
  for (let i = 0; i < x.length; i++) {
    if (g[i] < 0 && Number.isFinite(ub[i])) { v[i] = ub[i] - x[i]; dv[i] = -1; }
    if (g[i] > 0 && Number.isFinite(lb[i])) { v[i] = x[i] - lb[i]; dv[i] = 1; }
  }
  return [v, dv];
}

const matVec = (J, s) => J.map((row) => dot(row, s));
const gradOf = (J, f) => { const n = J[0].length, g = new Array(n).fill(0); for (let i = 0; i < J.length; i++) for (let j = 0; j < n; j++) g[j] += J[i][j] * f[i]; return g; };

function evaluateQuadratic(J, g, s, diag) {
  const Js = matVec(J, s);
  let q = dot(Js, Js);
  if (diag) q += dot(s.map((v, i) => v * diag[i]), s);
  return 0.5 * q + dot(s, g);
}

function buildQuadratic1d(J, g, s, diag = null, s0 = null) {
  const v = matVec(J, s);
  let a = dot(v, v);
  if (diag) a += dot(s.map((x, i) => x * diag[i]), s);
  a *= 0.5;
  let b = dot(g, s);
  if (s0) {
    const u = matVec(J, s0);
    b += dot(u, v);
    let c = 0.5 * dot(u, u) + dot(g, s0);
    if (diag) {
      b += dot(s0.map((x, i) => x * diag[i]), s);
      c += 0.5 * dot(s0.map((x, i) => x * diag[i]), s0);
    }
    return [a, b, c];
  }
  return [a, b];
}

function minimizeQuadratic1d(a, b, lb, ub, c = 0) {
  const t = [lb, ub];
  if (a !== 0) { const ext = -0.5 * b / a; if (lb < ext && ext < ub) t.push(ext); }
  let k = 0;
  const y = t.map((ti) => ti * (a * ti + b) + c);
  for (let i = 1; i < y.length; i++) if (y[i] < y[k]) k = i;
  return [t[k], y[k]];
}

function intersectTrustRegion(x, s, Delta) {
  const a = dot(s, s);
  if (a === 0) throw new Error("`s` is zero.");
  const b = dot(x, s);
  const c = dot(x, x) - Delta ** 2;
  if (c > 0) throw new Error("`x` is not within the trust region.");
  const d = Math.sqrt(b * b - a * c);
  const q = -(b + (b < 0 || Object.is(b, -0) ? -Math.abs(d) : Math.abs(d)));
  const t1 = q / a, t2 = c / q;
  return t1 < t2 ? [t1, t2] : [t2, t1];
}

function stepSizeToBound(x, s, lb, ub) {
  const steps = x.map((xi, i) => (s[i] !== 0 ? Math.max((lb[i] - xi) / s[i], (ub[i] - xi) / s[i]) : Infinity));
  let min = Infinity;
  for (const v of steps) if (v < min) min = v;
  const hits = steps.map((v, i) => (v === min ? Math.sign(s[i]) : 0));
  return [min, hits];
}

function solveLsqTrustRegion(n, m, uf, s, V, Delta, initialAlpha, rtol = 0.01, maxIter = 10) {
  const suf = s.map((v, i) => v * uf[i]);
  const phiAndDeriv = (alpha) => {
    const denom = s.map((v) => v * v + alpha);
    const pNorm = norm(suf.map((v, i) => v / denom[i]));
    let sum = 0;
    for (let i = 0; i < n; i++) sum += suf[i] ** 2 / denom[i] ** 3;
    return [pNorm - Delta, -sum / pNorm];
  };
  const fullRank = m >= n ? s[n - 1] > EPS * m * s[0] : false;
  const Vdot = (w) => { const out = new Array(n).fill(0); for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) out[i] += V[i][j] * w[j]; return out; };
  if (fullRank) {
    const p = Vdot(uf.map((v, i) => v / s[i])).map((v) => -v);
    if (norm(p) <= Delta) return [p, 0.0, 0];
  }
  let alphaUpper = norm(suf) / Delta;
  let alphaLower = 0.0;
  if (fullRank) { const [phi, dphi] = phiAndDeriv(0.0); alphaLower = -phi / dphi; }
  let alpha;
  if (initialAlpha === null || (!fullRank && initialAlpha === 0)) alpha = Math.max(0.001 * alphaUpper, (alphaLower * alphaUpper) ** 0.5);
  else alpha = initialAlpha;
  let it = 0;
  for (it = 0; it < maxIter; it++) {
    if (alpha < alphaLower || alpha > alphaUpper) alpha = Math.max(0.001 * alphaUpper, (alphaLower * alphaUpper) ** 0.5);
    const [phi, dphi] = phiAndDeriv(alpha);
    if (phi < 0) alphaUpper = alpha;
    const ratio = phi / dphi;
    alphaLower = Math.max(alphaLower, alpha - ratio);
    alpha -= (phi + Delta) * ratio / Delta;
    if (Math.abs(phi) < rtol * Delta) break;
  }
  let p = Vdot(suf.map((v, i) => v / (s[i] * s[i] + alpha))).map((v) => -v);
  const pn = norm(p);
  p = p.map((v) => v * (Delta / pn));
  return [p, alpha, it + 1];
}

function updateTrRadius(Delta, actual, predicted, stepNorm, boundHit) {
  let ratio;
  if (predicted > 0) ratio = actual / predicted;
  else if (predicted === actual && actual === 0) ratio = 1;
  else ratio = 0;
  if (ratio < 0.25) Delta = 0.25 * stepNorm;
  else if (ratio > 0.75 && boundHit) Delta *= 2.0;
  return [Delta, ratio];
}

function checkTermination(dF, F, dxNorm, xNorm, ratio, ftol, xtol) {
  const fOk = dF < ftol * F && ratio > 0.25;
  const xOk = dxNorm < xtol * (xtol + xNorm);
  if (fOk && xOk) return 4;
  if (fOk) return 2;
  if (xOk) return 3;
  return null;
}

function selectStep(x, Jh, diagH, gH, p, pH, d, Delta, lb, ub, theta) {
  const xp = x.map((v, i) => v + p[i]);
  if (inBounds(xp, lb, ub)) return [p, pH, -evaluateQuadratic(Jh, gH, pH, diagH)];

  const [pStride, hits] = stepSizeToBound(x, p, lb, ub);
  let rH = pH.map((v, i) => (hits[i] !== 0 ? -v : v));
  let r = rH.map((v, i) => d[i] * v);
  p = p.map((v) => v * pStride);
  pH = pH.map((v) => v * pStride);
  const xOnBound = x.map((v, i) => v + p[i]);
  const [, toTr0] = intersectTrustRegion(pH, rH, Delta);
  const [toBound0] = stepSizeToBound(xOnBound, r, lb, ub);
  let rStride = Math.min(toBound0, toTr0), rStrideL, rStrideU;
  if (rStride > 0) {
    rStrideL = (1 - theta) * pStride / rStride;
    rStrideU = rStride === toBound0 ? theta * toBound0 : toTr0;
  } else { rStrideL = 0; rStrideU = -1; }
  let rValue;
  if (rStrideL <= rStrideU) {
    const [a, b, c] = buildQuadratic1d(Jh, gH, rH, diagH, pH);
    [rStride, rValue] = minimizeQuadratic1d(a, b, rStrideL, rStrideU, c);
    rH = rH.map((v, i) => v * rStride + pH[i]);
    r = rH.map((v, i) => v * d[i]);
  } else rValue = Infinity;

  p = p.map((v) => v * theta);
  pH = pH.map((v) => v * theta);
  const pValue = evaluateQuadratic(Jh, gH, pH, diagH);

  let agH = gH.map((v) => -v);
  let ag = agH.map((v, i) => d[i] * v);
  const toTr = Delta / norm(agH);
  const [toBound] = stepSizeToBound(x, ag, lb, ub);
  let agStride = toBound < toTr ? theta * toBound : toTr;
  const [a2, b2] = buildQuadratic1d(Jh, gH, agH, diagH);
  let agValue;
  [agStride, agValue] = minimizeQuadratic1d(a2, b2, 0, agStride);
  agH = agH.map((v) => v * agStride);
  ag = ag.map((v) => v * agStride);

  if (pValue < rValue && pValue < agValue) return [p, pH, -pValue];
  if (rValue < pValue && rValue < agValue) return [r, rH, -rValue];
  return [ag, agH, -agValue];
}

/** 2-point forward-difference Jacobian with bounds (scipy approx_derivative, rel_step given). */
async function approxJacobian(fun, x0, f0, relStep, lb, ub, evalMany) {
  const n = x0.length;
  const rstep = Math.sqrt(EPS);
  let h = x0.map((x) => {
    const sign = x >= 0 ? 1 : -1;
    let abs = relStep * sign * Math.abs(x);
    if ((x + abs) - x === 0) abs = rstep * sign * Math.max(1.0, Math.abs(x));
    return abs;
  });
  // _adjust_scheme_to_bounds, '1-sided', num_steps = 1
  h = h.map((hi, i) => {
    const lower = x0[i] - lb[i], upper = ub[i] - x0[i];
    const xi = x0[i] + hi;
    const violated = xi < lb[i] || xi > ub[i];
    const fitting = Math.abs(hi) <= Math.max(lower, upper);
    if (violated && fitting) return -hi;
    if (!fitting) return upper >= lower ? upper : -lower;
    return hi;
  });
  const m = f0.length;
  const J = Array.from({ length: m }, () => new Float64Array(n));
  const points = [];
  for (let i = 0; i < n; i++) {
    const x1 = x0.slice();
    x1[i] = x0[i] + h[i];
    points.push(x1);
  }
  // The columns are independent, so evalMany may compute them in parallel
  // (same values as one at a time, so the result is identical).
  const fs = evalMany ? await evalMany(points) : points.map(fun);
  for (let i = 0; i < n; i++) {
    const dx = (x0[i] + h[i]) - x0[i];
    const f1 = fs[i];
    for (let k = 0; k < m; k++) J[k][i] = (f1[k] - f0[k]) / dx;
  }
  return J;
}

/**
 * least_squares(fun, x0, bounds=(lb, ub), method="trf", x_scale, diff_step, max_nfev)
 * with ftol = xtol = gtol = 1e-8. Resolves to { x, cost, nfev, status }.
 * evalMany(points) -> Promise<residual arrays> (optional) evaluates the
 * Jacobian's finite-difference points, e.g. spread over several workers.
 */
export async function leastSquaresTrf(fun, x0In, lb, ub, { xScale = 1.0, diffStep = null, maxNfev = null,
  ftol = 1e-8, xtol = 1e-8, gtol = 1e-8, evalMany = null } = {}) {
  if (!inBounds(x0In, lb, ub)) throw new Error("Initial guess is outside of provided bounds");
  const n = x0In.length;
  const scale = Array.isArray(xScale) ? xScale : new Array(n).fill(xScale);
  const scaleInv = scale.map((v) => 1 / v);
  const x0 = makeStrictlyFeasible(x0In, lb, ub);
  const relStep = diffStep;

  let x = x0.slice();
  let f = fun(x);
  if (!f.every(Number.isFinite)) throw new Error("Residuals are not finite in the initial point.");
  let nfev = 1;
  let J = await approxJacobian(fun, x, f, relStep, lb, ub, evalMany);
  const m = f.length;
  let cost = 0.5 * dot(f, f);
  let g = gradOf(J, f);

  let [v, dv] = clScalingVector(x, g, lb, ub);
  for (let i = 0; i < n; i++) if (dv[i] !== 0) v[i] *= scaleInv[i];
  let Delta = norm(x0.map((xi, i) => (xi * scaleInv[i]) / v[i] ** 0.5));
  if (Delta === 0) Delta = 1.0;
  let gNorm = normInf(g.map((gi, i) => gi * v[i]));
  if (maxNfev === null) maxNfev = n * 100;

  let alpha = 0.0, status = null;
  let costNew, xNew, fNew;
  for (;;) {
    [v, dv] = clScalingVector(x, g, lb, ub);
    gNorm = normInf(g.map((gi, i) => gi * v[i]));
    if (gNorm < gtol) status = 1;
    if (status !== null || nfev === maxNfev) break;

    for (let i = 0; i < n; i++) if (dv[i] !== 0) v[i] *= scaleInv[i];
    const d = v.map((vi, i) => vi ** 0.5 * scale[i]);
    const diagH = g.map((gi, i) => gi * dv[i] * scale[i]);
    const gH = d.map((di, i) => di * g[i]);

    const Jh = J.map((row) => Array.from(row, (val, j) => val * d[j]));
    const Jaug = Jh.concat(diagH.map((dh, i) => { const r = new Array(n).fill(0); r[i] = dh ** 0.5; return r; }));
    const fAug = Array.from(f).concat(new Array(n).fill(0));
    const { U, s, V } = svd(Jaug);
    const uf = new Array(n).fill(0);
    for (let i = 0; i < Jaug.length; i++) { const fi = fAug[i]; if (fi !== 0) for (let k = 0; k < n; k++) uf[k] += U[i][k] * fi; }

    const theta = Math.max(0.995, 1 - gNorm);
    let actual = -1;
    let stepHNorm;
    while (actual <= 0 && nfev < maxNfev) {
      let pH;
      [pH, alpha] = solveLsqTrustRegion(n, m, uf, s, V, Delta, alpha);
      const p = d.map((di, i) => di * pH[i]);
      const [step, stepH, predicted] = selectStep(x, Jh, diagH, gH, p, pH, d, Delta, lb, ub, theta);
      xNew = makeStrictlyFeasible(x.map((xi, i) => xi + step[i]), lb, ub, 0);
      fNew = fun(xNew);
      nfev += 1;
      stepHNorm = norm(stepH);
      if (!fNew.every(Number.isFinite)) { Delta = 0.25 * stepHNorm; continue; }
      costNew = 0.5 * dot(fNew, fNew);
      actual = cost - costNew;
      const [DeltaNew, ratio] = updateTrRadius(Delta, actual, predicted, stepHNorm, stepHNorm > 0.95 * Delta);
      const stepNorm = norm(step);
      status = checkTermination(actual, cost, stepNorm, norm(x), ratio, ftol, xtol);
      if (status !== null) break;
      alpha *= Delta / DeltaNew;
      Delta = DeltaNew;
    }
    if (actual > 0) {
      x = xNew; f = fNew; cost = costNew;
      J = await approxJacobian(fun, x, f, relStep, lb, ub, evalMany);
      g = gradOf(J, f);
    }
  }
  if (status === null) status = 0;
  return { x, cost, nfev, status };
}
