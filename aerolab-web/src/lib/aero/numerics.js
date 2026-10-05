// Numerical building blocks for the in-browser aeroelasticity solvers: the
// pieces of numpy/scipy that static_divergence.py, control_reversal.py and
// flutter_vg.py use, reimplemented to give the same results.

// ── PCHIP (scipy.interpolate.PchipInterpolator, extrapolate=False) ──────────
const sign = (v) => (v > 0 ? 1 : v < 0 ? -1 : 0);

function pchipEdge(h0, h1, m0, m1) {
  // scipy's _edge_case: one-sided three-point estimate, made shape-preserving
  let d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1);
  if (sign(d) !== sign(m0)) d = 0;
  else if (sign(m0) !== sign(m1) && Math.abs(d) > 3 * Math.abs(m0)) d = 3 * m0;
  return d;
}

/**
 * Monotone piecewise-cubic interpolant through (x[i], y[i]), x increasing.
 * Returns { at(a), deriv(a) } (NaN outside [x0, xn]) evaluating a number or array.
 */
export function pchip(xs, ys) {
  const x = Array.from(xs), y = Array.from(ys), n = x.length;
  const h = [], m = [];
  for (let i = 0; i < n - 1; i++) { h.push(x[i + 1] - x[i]); m.push((y[i + 1] - y[i]) / h[i]); }
  const d = new Array(n).fill(0);
  if (n === 2) { d[0] = m[0]; d[1] = m[0]; }
  else {
    for (let i = 1; i < n - 1; i++) {
      const m0 = m[i - 1], m1 = m[i];
      if (sign(m0) !== sign(m1) || m0 === 0 || m1 === 0) d[i] = 0;
      else {
        const w1 = 2 * h[i] + h[i - 1], w2 = h[i] + 2 * h[i - 1];
        d[i] = 1 / ((w1 / m0 + w2 / m1) / (w1 + w2));
      }
    }
    d[0] = pchipEdge(h[0], h[1], m[0], m[1]);
    d[n - 1] = pchipEdge(h[n - 2], h[n - 3], m[n - 2], m[n - 3]);
  }
  // Cubic coefficients per interval (CubicHermiteSpline form)
  const c2 = [], c3 = [];
  for (let i = 0; i < n - 1; i++) {
    c2.push((3 * m[i] - 2 * d[i] - d[i + 1]) / h[i]);
    c3.push((d[i] + d[i + 1] - 2 * m[i]) / (h[i] * h[i]));
  }
  const find = (a) => {
    if (!(a >= x[0] && a <= x[n - 1])) return -1;
    // scipy: interval i with x[i] <= a < x[i+1]; the right end uses the last one
    let lo = 0, hi = n - 2;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (x[mid] <= a) lo = mid; else hi = mid - 1;
    }
    return lo;
  };
  const one = (a, der) => {
    const i = find(a);
    if (i < 0) return NaN;
    const t = a - x[i];
    return der ? d[i] + t * (2 * c2[i] + 3 * c3[i] * t) : y[i] + t * (d[i] + t * (c2[i] + t * c3[i]));
  };
  const map = (a, der) => (Array.isArray(a) || ArrayBuffer.isView(a) ? Array.from(a, (v) => one(v, der)) : one(a, der));
  return { at: (a) => map(a, false), deriv: (a) => map(a, true), x, y };
}

// ── numpy helpers ───────────────────────────────────────────────────────────
/** np.interp (xp increasing; clamps outside the range). */
export function interp(v, xp, fp) {
  const n = xp.length;
  if (v <= xp[0]) return fp[0];
  if (v >= xp[n - 1]) return fp[n - 1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xp[mid] <= v) lo = mid; else hi = mid; }
  const slope = (fp[hi] - fp[lo]) / (xp[hi] - xp[lo]);
  return fp[lo] + slope * (v - xp[lo]);
}

/** Least-squares straight line y = a*x + b; returns a (np.linalg.lstsq on [x, 1]). */
export function lsqSlope(xs, ys) {
  const n = xs.length;
  let sx = 0, sy = 0;
  for (let i = 0; i < n; i++) { sx += xs[i]; sy += ys[i]; }
  const mx = sx / n, my = sy / n;
  let sxx = 0, sxy = 0;
  for (let i = 0; i < n; i++) { const dx = xs[i] - mx; sxx += dx * dx; sxy += dx * (ys[i] - my); }
  return sxy / sxx;
}

/** np.linspace(a, b, n) */
export function linspace(a, b, n) {
  if (n === 1) return [a];
  const out = new Array(n), step = (b - a) / (n - 1);
  for (let i = 0; i < n; i++) out[i] = a + i * step;
  out[n - 1] = b;
  return out;
}

/** Python round() (half to even) to `nd` decimals. */
export function pyRound(v, nd = 0) {
  const f = 10 ** nd, s = v * f, r = Math.round(s);
  return (Math.abs(s - Math.trunc(s)) === 0.5 && r % 2 !== 0 ? r - 1 : r) / f;
}

// ── Complex numbers (just what the flutter solver needs) ────────────────────
export const C = {
  of: (re, im = 0) => ({ re, im }),
  add: (a, b) => ({ re: a.re + b.re, im: a.im + b.im }),
  sub: (a, b) => ({ re: a.re - b.re, im: a.im - b.im }),
  mul: (a, b) => ({ re: a.re * b.re - a.im * b.im, im: a.re * b.im + a.im * b.re }),
  scale: (a, s) => ({ re: a.re * s, im: a.im * s }),
  div: (a, b) => {
    const den = b.re * b.re + b.im * b.im;
    return { re: (a.re * b.re + a.im * b.im) / den, im: (a.im * b.re - a.re * b.im) / den };
  },
  abs: (a) => Math.hypot(a.re, a.im),
};

// ── Bessel functions J0, J1, Y0, Y1 for real x > 0 ──────────────────────────
// Power series for x < 12, Hankel asymptotic expansion above (both accurate
// to ~1e-13 relative over the reduced-frequency range flutter needs).
const EULER = 0.5772156649015329;

function besselSeries(x) {
  const q = (x * x) / 4;
  // J0, J1
  let j0 = 0, j1 = 0, t0 = 1, t1 = x / 2;
  for (let k = 0; k < 200; k++) {
    if (k > 0) { t0 *= -q / (k * k); t1 *= -q / (k * (k + 1)); }
    j0 += t0; j1 += t1;
    if (Math.abs(t0) < 1e-17 * Math.abs(j0) && Math.abs(t1) < 1e-17 * Math.abs(j1) && k > 2) break;
  }
  // Y0 = (2/pi)[(ln(x/2)+g) J0 + sum_{k>=1} (-1)^{k+1} H_k q^k/(k!)^2]
  let s0 = 0, term = 1, H = 0;
  for (let k = 1; k < 200; k++) {
    term *= q / (k * k); H += 1 / k;
    const add = (k % 2 === 1 ? 1 : -1) * H * term;
    s0 += add;
    if (Math.abs(add) < 1e-17 * Math.abs(s0) && k > 2) break;
  }
  const lg = Math.log(x / 2) + EULER;
  const y0 = (2 / Math.PI) * (lg * j0 + s0);
  // Y1 = -2/(pi x) + (2/pi) ln(x/2) J1 - (1/pi) sum_{k>=0} (-1)^k [psi(k+1)+psi(k+2)] (x/2)^{2k+1}/(k!(k+1)!)
  let s1 = 0, t = x / 2, Hk = 0; // Hk = H_k
  for (let k = 0; k < 200; k++) {
    if (k > 0) { t *= -q / (k * (k + 1)); Hk += 1 / k; }
    const psiSum = (-EULER + Hk) + (-EULER + Hk + 1 / (k + 1));
    const add = psiSum * t;
    s1 += add;
    if (Math.abs(add) < 1e-17 * Math.abs(s1) && k > 2) break;
  }
  const y1 = -2 / (Math.PI * x) + (2 / Math.PI) * Math.log(x / 2) * j1 - s1 / Math.PI;
  return { j0, j1, y0, y1 };
}

function besselAsymptotic(x) {
  // J_n = sqrt(2/(pi x)) (P cos w - Q sin w), Y_n = sqrt(2/(pi x)) (P sin w + Q cos w),
  // w = x - (2n+1) pi/4
  const out = {};
  for (const nu of [0, 1]) {
    const mu = 4 * nu * nu;
    let P = 1, Q = 0, term = 1;
    for (let k = 1; k < 30; k++) {
      term *= (mu - (2 * k - 1) ** 2) / (k * 8 * x);
      const prevAbs = Math.abs(term);
      if (k % 2 === 1) Q += (k % 4 === 1 ? 1 : -1) * term;
      else P += (k % 4 === 2 ? -1 : 1) * term;
      if (prevAbs < 1e-17) break;
    }
    const w = x - (2 * nu + 1) * Math.PI / 4;
    const amp = Math.sqrt(2 / (Math.PI * x));
    out[`j${nu}`] = amp * (P * Math.cos(w) - Q * Math.sin(w));
    out[`y${nu}`] = amp * (P * Math.sin(w) + Q * Math.cos(w));
  }
  return out;
}

export function bessel01(x) {
  return x < 12 ? besselSeries(x) : besselAsymptotic(x);
}

/** Theodorsen's function C(k) = H1(2)(k) / [H1(2)(k) + i H0(2)(k)], H(2) = J - iY. */
export function theodorsenC(k) {
  if (k === 0) return C.of(1, 0);
  const { j0, j1, y0, y1 } = bessel01(k);
  const H1 = C.of(j1, -y1), H0 = C.of(j0, -y0);
  const iH0 = C.of(-H0.im, H0.re);
  return C.div(H1, C.add(H1, iH0));
}

// ── Roots of a complex polynomial (Aberth–Ehrlich + Newton polish) ──────────
/** coeffs: [a_n, ..., a_0] complex. Returns the n complex roots. */
export function polyRoots(coeffs) {
  const n = coeffs.length - 1;
  const lead = coeffs[0];
  const a = coeffs.map((c) => C.div(c, lead));
  const evalP = (z) => {
    let p = C.of(0), dp = C.of(0);
    for (const c of a) { dp = C.add(C.mul(dp, z), p); p = C.add(C.mul(p, z), c); }
    return { p, dp };
  };
  // Cauchy bound for the initial circle
  let R = 0;
  for (let i = 1; i <= n; i++) R = Math.max(R, C.abs(a[i]));
  R = 1 + R;
  let z = [];
  for (let i = 0; i < n; i++) {
    const th = (2 * Math.PI * i) / n + 0.4;
    z.push(C.of(R * 0.5 * Math.cos(th), R * 0.5 * Math.sin(th)));
  }
  for (let it = 0; it < 500; it++) {
    let maxStep = 0;
    const next = z.map((zi, i) => {
      const { p, dp } = evalP(zi);
      if (C.abs(p) === 0) return zi;
      const ratio = C.div(p, dp);
      let sum = C.of(0);
      for (let j = 0; j < n; j++) if (j !== i) sum = C.add(sum, C.div(C.of(1), C.sub(zi, z[j])));
      const w = C.div(ratio, C.sub(C.of(1), C.mul(ratio, sum)));
      maxStep = Math.max(maxStep, C.abs(w) / Math.max(1, C.abs(zi)));
      return C.sub(zi, w);
    });
    z = next;
    if (maxStep < 1e-15) break;
  }
  // Newton polish on the full polynomial
  return z.map((zi) => {
    for (let k = 0; k < 3; k++) {
      const { p, dp } = evalP(zi);
      if (C.abs(dp) === 0) break;
      zi = C.sub(zi, C.div(p, dp));
    }
    return zi;
  });
}

/**
 * Python's f"{v:.{d}f}": like toFixed, but exact halfway cases round to even
 * (Python formats the exact binary value; toFixed rounds those up).
 * Throws on null/undefined, as Python's format() does on None.
 */
export function pyFixed(v, d) {
  if (v === null || v === undefined) throw new TypeError("unsupported format string passed to NoneType.__format__");
  if (!Number.isFinite(v)) return Number.isNaN(v) ? "nan" : v > 0 ? "inf" : "-inf";
  const exact = Math.abs(v).toFixed(100);
  const dot = exact.indexOf(".");
  const tail = exact.slice(dot + 1 + d);
  if (tail[0] === "5" && /^50*$/.test(tail)) {
    // exact tie: keep the even neighbour
    const down = Math.abs(v).toFixed(100).slice(0, dot + 1 + d).replace(/\.$/, "");
    const lastDigit = Number((d === 0 ? exact.slice(0, dot) : down).slice(-1));
    const up = (Math.abs(v) + 0.5 * 10 ** -d).toFixed(d);
    const s = lastDigit % 2 === 0 ? (d === 0 ? exact.slice(0, dot) : down) : up;
    return (v < 0 && Number(s) !== 0 ? "-" : v < 0 ? "-" : "") + s;
  }
  const s = v.toFixed(d);
  return s === `-${(0).toFixed(d)}` ? s : s;
}
