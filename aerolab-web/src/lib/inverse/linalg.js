// Dense linear algebra for the inverse-design solver (what numpy/LAPACK did
// in inverse_design.py): LU solve, least squares via Householder QR, thin SVD.
// Matrices are arrays of rows (Float64Array or plain arrays).

export const EPS = 2.220446049250313e-16;

export const dot = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };

/** Euclidean norm, scaled to avoid overflow (like LAPACK's dnrm2). */
export function norm(v) {
  let scale = 0, ssq = 1;
  for (let i = 0; i < v.length; i++) {
    const x = v[i];
    if (x !== 0) {
      const a = Math.abs(x);
      if (scale < a) { ssq = 1 + ssq * (scale / a) ** 2; scale = a; } else ssq += (a / scale) ** 2;
    }
  }
  return scale * Math.sqrt(ssq);
}

export const normInf = (v) => { let m = 0; for (const x of v) m = Math.max(m, Math.abs(x)); return m; };

/** Solve A x = b (A square, rows), Gaussian elimination with partial pivoting (as LAPACK gesv). */
export function solve(A, b) {
  const n = A.length;
  const M = A.map((r) => Float64Array.from(r));
  const x = Float64Array.from(b);
  for (let k = 0; k < n; k++) {
    let p = k, big = Math.abs(M[k][k]);
    for (let i = k + 1; i < n; i++) { const v = Math.abs(M[i][k]); if (v > big) { big = v; p = i; } }
    if (big === 0) throw new Error("Singular matrix");
    if (p !== k) { [M[k], M[p]] = [M[p], M[k]]; [x[k], x[p]] = [x[p], x[k]]; }
    const rk = M[k], piv = rk[k];
    for (let i = k + 1; i < n; i++) {
      const ri = M[i], f = ri[k] / piv;
      if (f === 0) continue;
      ri[k] = f;
      for (let j = k + 1; j < n; j++) ri[j] -= f * rk[j];
      x[i] -= f * x[k];
    }
  }
  for (let k = n - 1; k >= 0; k--) {
    const rk = M[k];
    let s = x[k];
    for (let j = k + 1; j < n; j++) s -= rk[j] * x[j];
    x[k] = s / rk[k];
  }
  return x;
}

/** Least-squares solution of A x ~ b (A: m x n, m >= n, full column rank) via Householder QR. */
export function lstsq(A, b) {
  const m = A.length, n = A[0].length;
  const R = A.map((r) => Float64Array.from(r));
  const y = Float64Array.from(b);
  for (let k = 0; k < n; k++) {
    let s = 0;
    for (let i = k; i < m; i++) s += R[i][k] * R[i][k];
    const alpha = -Math.sign(R[k][k] || 1) * Math.sqrt(s);
    const v = new Float64Array(m - k);
    for (let i = k; i < m; i++) v[i - k] = R[i][k];
    v[0] -= alpha;
    const vn = dot(v, v);
    if (vn === 0) continue;
    for (let j = k; j < n; j++) {
      let t = 0;
      for (let i = k; i < m; i++) t += v[i - k] * R[i][j];
      t = (2 * t) / vn;
      for (let i = k; i < m; i++) R[i][j] -= t * v[i - k];
    }
    let t = 0;
    for (let i = k; i < m; i++) t += v[i - k] * y[i];
    t = (2 * t) / vn;
    for (let i = k; i < m; i++) y[i] -= t * v[i - k];
  }
  const x = new Float64Array(n);
  for (let k = n - 1; k >= 0; k--) {
    let s = y[k];
    for (let j = k + 1; j < n; j++) s -= R[k][j] * x[j];
    x[k] = s / R[k][k];
  }
  return x;
}

/**
 * Thin SVD of A (m x n, m >= n) by one-sided Jacobi rotations.
 * Returns { U: m x n (rows), s: n (descending), V: n x n (rows; columns are right singular vectors) }.
 */
export function svd(A) {
  const m = A.length, n = A[0].length;
  // Work on columns
  const cols = [];
  for (let j = 0; j < n; j++) { const c = new Float64Array(m); for (let i = 0; i < m; i++) c[i] = A[i][j]; cols.push(c); }
  const Vc = [];
  for (let j = 0; j < n; j++) { const c = new Float64Array(n); c[j] = 1; Vc.push(c); }
  for (let sweep = 0; sweep < 60; sweep++) {
    let off = 0;
    for (let p = 0; p < n - 1; p++) {
      for (let q = p + 1; q < n; q++) {
        const a = cols[p], b = cols[q];
        let alpha = 0, beta = 0, gamma = 0;
        for (let i = 0; i < m; i++) { alpha += a[i] * a[i]; beta += b[i] * b[i]; gamma += a[i] * b[i]; }
        if (gamma === 0) continue;
        const conv = Math.abs(gamma) / Math.sqrt(alpha * beta);
        if (!(conv > 1e-15)) continue;
        off = Math.max(off, conv);
        const zeta = (beta - alpha) / (2 * gamma);
        const t = Math.sign(zeta || 1) / (Math.abs(zeta) + Math.sqrt(1 + zeta * zeta));
        const c = 1 / Math.sqrt(1 + t * t), s = c * t;
        for (let i = 0; i < m; i++) { const ai = a[i], bi = b[i]; a[i] = c * ai - s * bi; b[i] = s * ai + c * bi; }
        const va = Vc[p], vb = Vc[q];
        for (let i = 0; i < n; i++) { const ai = va[i], bi = vb[i]; va[i] = c * ai - s * bi; vb[i] = s * ai + c * bi; }
      }
    }
    if (off < 1e-15) break;
  }
  const order = cols.map((c, j) => [norm(c), j]).sort((p, q) => q[0] - p[0]);
  const s = new Float64Array(n);
  const U = Array.from({ length: m }, () => new Float64Array(n));
  const V = Array.from({ length: n }, () => new Float64Array(n));
  order.forEach(([sv, j], k) => {
    s[k] = sv;
    for (let i = 0; i < m; i++) U[i][k] = sv > 0 ? cols[j][i] / sv : 0;
    for (let i = 0; i < n; i++) V[i][k] = Vc[j][i];
  });
  return { U, s, V };
}
