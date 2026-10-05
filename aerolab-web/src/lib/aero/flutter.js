// 2-DOF pitch + plunge flutter, p-k method with Theodorsen's exact unsteady
// airload. JavaScript port of the backend's flutter_vg.py (Berci 2021,
// Eq. 1 and Eq. 25; same sign conventions); keep the two in step.

import { C, linspace, polyRoots, pyFixed, theodorsenC } from "./numerics.js";
import { XfoilPolarError, runPolar } from "./divergence.js";

export const PLOT_POINTS = 120;

const PI = Math.PI;
const cx = (re, im = 0) => C.of(re, im);
const sub2 = (A, B) => A.map((r, i) => r.map((v, j) => C.sub(v, B[i][j])));
const neg2 = (A) => A.map((r) => r.map((v) => C.scale(v, -1)));

/** Structural + aerodynamic matrices (flutter_vg.build_matrices). */
export function buildMatrices(m, mu, xCG, xEA, kh, ktheta, b, rho, U, k, a0Scale = 1.0) {
  const Ck = theodorsenC(k);
  const d = xCG - xEA;
  const Ms = [[cx(m), cx(-m * d)], [cx(-m * d), cx(mu + m * d ** 2)]];
  const Ks = [[cx(kh), cx(0)], [cx(0), cx(ktheta)]];
  const Ma = [
    [cx(-PI * rho * b ** 2), cx(-PI * rho * b ** 2 * xEA)],
    [cx(-PI * rho * b ** 2 * xEA), cx(-PI * rho * b ** 2 * (b ** 2 / 8 + xEA ** 2))],
  ];
  // Same operation order as the Python expressions (real factors, then C(k), then a0_scale)
  const ck = (f) => C.scale(Ck, f);
  const Ca = [
    [C.scale(ck(-2 * PI * rho * U * b), a0Scale),
      C.add(C.scale(C.scale(ck(2 * PI * rho * U * b), b / 2 - xEA), a0Scale), cx(PI * rho * b ** 2 * U))],
    [C.scale(ck(-2 * PI * rho * U * b * (b / 2 + xEA)), a0Scale),
      C.sub(C.scale(C.scale(ck(2 * PI * rho * U * b * (b / 2 + xEA)), b / 2 - xEA), a0Scale),
        cx(PI * rho * b ** 2 * (b / 2 - xEA) * U))],
  ];
  const Ka = [
    [cx(0), C.scale(ck(2 * PI * rho * U ** 2 * b), a0Scale)],
    [cx(0), C.scale(ck(2 * PI * rho * U ** 2 * b * (b / 2 + xEA)), a0Scale)],
  ];
  return { M: sub2(Ms, Ma), Cm: neg2(Ca), K: sub2(Ks, Ka) };
}

/** Eigenvalues s of the system: roots of det(s^2 M + s C + K) = 0 (the 4 eigenvalues of the state matrix). */
export function systemEigenvalues(M, Cm, K) {
  const p = (i, j) => [M[i][j], Cm[i][j], K[i][j]];
  const mul = (a, b) => {
    const r = [cx(0), cx(0), cx(0), cx(0), cx(0)];
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) r[i + j] = C.add(r[i + j], C.mul(a[i], b[j]));
    return r;
  };
  const A = mul(p(0, 0), p(1, 1)), B = mul(p(0, 1), p(1, 0));
  return polyRoots(A.map((v, i) => C.sub(v, B[i])));
}

function trackSingleMode(m, mu, xCG, xEA, kh, ktheta, b, rho, U, omegaTarget, maxIters = 60, tol = 1e-6, a0Scale = 1.0) {
  let k = U > 0 ? b * omegaTarget / U : 0.0;
  let crit = null;
  for (let it = 0; it < maxIters; it++) {
    const { M, Cm, K } = buildMatrices(m, mu, xCG, xEA, kh, ktheta, b, rho, U, k, a0Scale);
    const physical = systemEigenvalues(M, Cm, K).filter((z) => z.im > 1e-8);
    if (!physical.length) return { omega: null, damping: null, k: null, converged: false };
    crit = physical[0];
    for (const z of physical) if (Math.abs(z.im - omegaTarget) < Math.abs(crit.im - omegaTarget)) crit = z;
    const newOmega = crit.im;
    const newK = U > 0 ? b * newOmega / U : 0.0;
    if (Math.abs(newK - k) < tol) return { omega: newOmega, damping: crit.re, k: newK, converged: true };
    k = newK;
    omegaTarget = newOmega;
  }
  return { omega: omegaTarget, damping: crit !== null ? crit.re : null, k, converged: false };
}

export function solveModesAtSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, a0Scale = 1.0) {
  const omegaH = Math.sqrt(kh / m);
  const muTheta = mu + m * (xCG - xEA) ** 2;
  const omegaTheta = Math.sqrt(ktheta / muTheta);
  return [
    trackSingleMode(m, mu, xCG, xEA, kh, ktheta, b, rho, U, omegaH, 60, 1e-6, a0Scale),
    trackSingleMode(m, mu, xCG, xEA, kh, ktheta, b, rho, U, omegaTheta, 60, 1e-6, a0Scale),
  ];
}

const mostCritical = (cands) => cands.reduce((best, r) => (best === null || r.damping > best.damping ? r : best), null);

export function solveAtSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, a0Scale = 1.0) {
  const cands = solveModesAtSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, a0Scale).filter((r) => r.converged);
  if (!cands.length) return { omega: null, damping: null, k: null, converged: false };
  return mostCritical(cands);
}

function modeEntry(r) {
  if (!r.converged) return null;
  return { damping: r.damping, omega: r.omega, freq_hz: r.omega / (2 * PI), k: r.k };
}

export function findFlutterSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, UStart = 0.1, UStep = 0.05, UMax = 50.0, a0Scale = 1.0) {
  const history = [], modes = [], skipped = [];
  let prevDamping = null, U = UStart, firstChecked = false;
  const done = (reason, Uf = null, omega = null, k = null, critical = null) => ({
    U_flutter: Uf, omega_flutter: omega, k_flutter: k, stopped_reason: reason,
    history, modes, skipped_speeds: skipped, critical_mode: critical,
  });

  while (U <= UMax + 1e-12) {
    const [rh, rt] = solveModesAtSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, a0Scale);
    modes.push({ U, plunge: modeEntry(rh), pitch: modeEntry(rt) });
    const cands = [rh, rt].filter((r) => r.converged);
    if (!cands.length) { skipped.push(U); U += UStep; continue; }
    const result = mostCritical(cands);
    const damping = result.damping;
    history.push([U, damping, result.omega, result.k]);

    if (!firstChecked) {
      firstChecked = true;
      if (damping >= 0) return done("unstable_at_start");
    }

    if (prevDamping !== null && prevDamping < 0 && 0 <= damping) {
      let ULo = U - UStep, UHi = U, dLo = prevDamping;
      for (let i = 0; i < 20; i++) {
        const UMid = 0.5 * (ULo + UHi);
        const mid = solveAtSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, UMid, a0Scale);
        if (!mid.converged) break;
        const dMid = mid.damping;
        if (dLo < 0 && 0 <= dMid) UHi = UMid;
        else { ULo = UMid; dLo = dMid; }
      }
      const UFlutter = 0.5 * (ULo + UHi);
      const [fh, ft] = solveModesAtSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, UFlutter, a0Scale);
      const conv = [["plunge", fh], ["pitch", ft]].filter(([, r]) => r.converged);
      let critical = null, final = { omega: null, k: null };
      if (conv.length) {
        let best = conv[0];
        for (const c of conv) if (c[1].damping > best[1].damping) best = c;
        [critical, final] = best;
      }
      return done("flutter_found", UFlutter, final.omega, final.k, critical);
    }
    prevDamping = damping;
    U += UStep;
  }
  return done("no_flutter_in_range");
}

export async function getRealAeroParams(runXfoil, seed, reynolds, ncrit, alphaRef) {
  const polar = await runPolar(runXfoil, seed, reynolds, ncrit, {
    alphaMin: alphaRef - 5.0, alphaMax: alphaRef + 5.0, alphaStep: 0.5, anchorAlpha: alphaRef, tag: "flutter",
  });
  if (!polar.contains(alphaRef)) {
    throw new XfoilPolarError(`XFOIL did not converge near alpha_ref=${alphaRef} deg`);
  }
  const p = polar.aeroParams(alphaRef);
  const a0 = p.a0_per_rad;
  return {
    a0_per_rad: a0, a0_scale: a0 / (2 * PI),
    x_ac_over_c: p.x_ac_over_c, x_ac_deviation_from_quarter_chord: p.x_ac_over_c - 0.25,
  };
}

const fmtG = (v) => {
  // Python's :g for the speeds shown in messages
  if (v === 0) return "0";
  const s = Number(v.toPrecision(6));
  return String(s).replace(/e\+?(-?)(\d)$/, "e$1" + "0$2");
};

export async function analyzeFlutter(runXfoil, seed, reynolds, ncrit, alphaRef, m, mu, xCG, xEA, kh, ktheta, b, rho,
  useRealAirfoilData = true, UStart = 0.5, UStep = 0.5, UMax = 100.0) {
  const warnings = [];
  let aeroInfo = null, a0Scale = 1.0;
  if (useRealAirfoilData) {
    aeroInfo = await getRealAeroParams(runXfoil, seed, reynolds, ncrit, alphaRef);
    a0Scale = aeroInfo.a0_scale;
    if (Math.abs(aeroInfo.x_ac_deviation_from_quarter_chord) > 0.02) {
      warnings.push(
        `This airfoil's aerodynamic centre is at ${pyFixed(aeroInfo.x_ac_over_c * 100, 1)}% `
        + "chord, not 25%. The unsteady (Theodorsen) model assumes 25%, so treat the "
        + "flutter speed as approximate.");
    }
  }

  const result = findFlutterSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, UStart, UStep, UMax, a0Scale);

  let UEnd;
  if (result.stopped_reason === "flutter_found") UEnd = Math.min(UMax, 1.3 * result.U_flutter);
  else if (result.stopped_reason === "unstable_at_start") UEnd = UStart;
  else UEnd = UMax;
  if (UEnd > UStart) {
    result.modes = linspace(UStart, UEnd, PLOT_POINTS).map((U) => {
      const [rh, rt] = solveModesAtSpeed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, a0Scale);
      return { U, plunge: modeEntry(rh), pitch: modeEntry(rt) };
    });
  }

  if (result.stopped_reason === "unstable_at_start") {
    warnings.push(
      `The section is already unstable at the first swept speed (${fmtG(UStart)} m/s), so `
      + "the flutter speed is below it. Lower 'Sweep from'.");
  }
  if (result.skipped_speeds.length) {
    const s = result.skipped_speeds;
    warnings.push(
      `The p-k iteration did not converge at ${s.length} of the swept speeds `
      + `(e.g. ${fmtG(s[0])} m/s); they are left out of the plots.`);
  }

  const omegaH = Math.sqrt(kh / m);
  const omegaTheta = Math.sqrt(ktheta / (mu + m * (xCG - xEA) ** 2));
  if (xCG <= xEA) {
    warnings.push(
      "The centre of gravity is at or ahead of the elastic axis. Classical "
      + "bending-torsion flutter usually needs the CG aft of the elastic axis.");
  }

  Object.assign(result, {
    aero_info: aeroInfo,
    a0_scale: a0Scale,
    uncoupled: { omega_h: omegaH, omega_theta: omegaTheta, freq_ratio: omegaTheta ? omegaH / omegaTheta : null },
    warnings,
  });
  return result;
}
