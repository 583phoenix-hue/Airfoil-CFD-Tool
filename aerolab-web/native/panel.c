// Linear-strength vortex panel method (Katz & Plotkin VOR2DL) for AeroLab's
// inverse design, compiled to WebAssembly. Same arithmetic, in the same
// order, as panelCp() in inverse.js; atan2/log come from JavaScript's Math
// so the results are bit-identical to the JS version.
// Build: see build_panel.sh
typedef unsigned long size_t;
extern double js_atan2(double, double) __attribute__((import_module("env"), import_name("atan2")));
extern double js_log(double) __attribute__((import_module("env"), import_name("log")));
extern double js_cos(double) __attribute__((import_module("env"), import_name("cos")));
extern double js_sin(double) __attribute__((import_module("env"), import_name("sin")));
extern unsigned char __heap_base;

static double *heap(void) { return (double *)(((size_t)&__heap_base + 15) & ~(size_t)15); }

/* Ensure memory for `doubles` doubles past the heap base; returns the pointer (0 on failure). */
__attribute__((export_name("reserve"))) double *reserve(int doubles) {
  size_t need = (size_t)heap() + (size_t)doubles * 8;
  size_t have = __builtin_wasm_memory_size(0) * 65536;
  if (need > have) {
    if (__builtin_wasm_memory_grow(0, (need - have + 65535) / 65536) == (size_t)-1) return 0;
  }
  return heap();
}

/* In: xs[N], ys[N] (Selig order) at the start of the reserved block.
   Out: cp[n], xc[n], yc[n] (Selig order, n = N-1) right after them.
   Returns 0, or 1 for a singular matrix. */
__attribute__((export_name("panel_cp"))) int panel_cp(int N, double alpha) {
  const double PI = 3.14159265358979323846;
  int n = N - 1, m = n + 1;
  double *xs = heap(), *ys = xs + N, *cpo = ys + N, *xco = cpo + n, *yco = xco + n;
  double *x = yco + n, *y = x + N, *xc = y + N, *yc = xc + n, *len = yc + n, *cj = len + n, *sj = cj + n;
  double *g = sj + n, *A = g + m, *B = A + (size_t)m * m;
  for (int i = 0; i < N; i++) { x[i] = xs[N - 1 - i]; y[i] = ys[N - 1 - i]; }
  double a = alpha * (PI / 180);
  for (int j = 0; j < n; j++) {
    double ddx = x[j + 1] - x[j], ddy = y[j + 1] - y[j];
    double th = js_atan2(ddy, ddx);
    xc[j] = 0.5 * (x[j] + x[j + 1]); yc[j] = 0.5 * (y[j] + y[j + 1]);
    cj[j] = js_cos(th); sj[j] = js_sin(th);
    len[j] = __builtin_sqrt(ddx * ddx + ddy * ddy);
  }
  for (size_t k = 0; k < (size_t)m * m; k++) A[k] = 0;
  for (size_t k = 0; k < (size_t)n * m; k++) B[k] = 0;
  double inv2pi = 1 / (2 * PI);
  for (int i = 0; i < n; i++) {
    double ci = cj[i], si = sj[i], xci = xc[i], yci = yc[i];
    double *Ar = A + (size_t)i * m, *Br = B + (size_t)i * m;
    for (int j = 0; j < n; j++) {
      double dx = xci - x[j], dy = yci - y[j], c = cj[j], s = sj[j];
      double X = dx * c + dy * s, Y = -dx * s + dy * c, X2 = len[j];
      double U1L, U2L, W1L, W2L;
      if (i == j) {
        U1L = -0.5 * (X - X2) / X2; U2L = 0.5 * X / X2;
        W1L = -inv2pi; W2L = inv2pi;
      } else {
        double XmX2 = X - X2, Y2 = Y * Y;
        double dTH = js_atan2(Y, XmX2) - js_atan2(Y, X);
        double LN = 0.5 * js_log((XmX2 * XmX2 + Y2) / (X * X + Y2));
        double tp = inv2pi / X2;
        U1L = -(Y * LN + X * dTH - X2 * dTH) * tp; U2L = (Y * LN + X * dTH) * tp;
        W1L = -((X2 - Y * dTH) + X * LN - X2 * LN) * tp; W2L = ((X2 - Y * dTH) + X * LN) * tp;
      }
      double u1 = U1L * c - W1L * s, w1 = U1L * s + W1L * c;
      double u2 = U2L * c - W2L * s, w2 = U2L * s + W2L * c;
      Ar[j] += -u1 * si + w1 * ci; Br[j] += u1 * ci + w1 * si;
      Ar[j + 1] += -u2 * si + w2 * ci; Br[j + 1] += u2 * ci + w2 * si;
    }
  }
  A[(size_t)n * m] = 1.0; A[(size_t)n * m + n] = 1.0; /* Kutta condition */
  double ca = js_cos(a), sa = js_sin(a);
  for (int i = 0; i < n; i++) g[i] = ca * sj[i] - sa * cj[i];
  g[n] = 0;
  /* LU with partial pivoting, in place */
  for (int k = 0; k < m; k++) {
    int p = k; double big = __builtin_fabs(A[(size_t)k * m + k]);
    for (int i = k + 1; i < m; i++) { double v = __builtin_fabs(A[(size_t)i * m + k]); if (v > big) { big = v; p = i; } }
    if (big == 0) return 1;
    if (p != k) {
      double *rk = A + (size_t)k * m, *rp = A + (size_t)p * m;
      for (int j = 0; j < m; j++) { double t = rk[j]; rk[j] = rp[j]; rp[j] = t; }
      double t = g[k]; g[k] = g[p]; g[p] = t;
    }
    double *rk = A + (size_t)k * m, piv = rk[k];
    for (int i = k + 1; i < m; i++) {
      double *ri = A + (size_t)i * m, f = ri[k] / piv;
      if (f == 0) continue;
      ri[k] = f;
      for (int j = k + 1; j < m; j++) ri[j] -= f * rk[j];
      g[i] -= f * g[k];
    }
  }
  for (int k = m - 1; k >= 0; k--) {
    double *rk = A + (size_t)k * m, s = g[k];
    for (int j = k + 1; j < m; j++) s -= rk[j] * g[j];
    g[k] = s / rk[k];
  }
  for (int i = 0; i < n; i++) {
    double sum = 0, *Br = B + (size_t)i * m;
    for (int j = 0; j < m; j++) sum += Br[j] * g[j];
    double vt = sum + ca * cj[i] + sa * sj[i];
    cpo[n - 1 - i] = 1.0 - vt * vt; xco[n - 1 - i] = xc[i]; yco[n - 1 - i] = yc[i];
  }
  return 0;
}
