"""
inverse_design.py
==================

AeroLab inverse design: find the airfoil whose surface pressure matches a
drawn target Cp(x/c) at a given Reynolds number and angle of attack.

Rebuilt 2026-09 following SU2's Cp inverse-design approach
(OBJECTIVE_FUNCTION = INVERSE_DESIGN_PRESSURE, see SU2
CFlowOutput::SetCpInverseDesign and TestCases/optimization_euler/
steady_inverse_design), adapted to a panel-method + XFOIL setting:

  SU2                                   AeroLab
  ------------------------------------  --------------------------------------
  objective sum_i A_i (Cp_t - Cp)^2     same, over every surface panel
    over every surface vertex             (A_i = panel length)
  shape design variables (FFD /         CST (Kulfan) coefficients per surface
    Hicks-Henne / CST), bounded           (SU2's CST DV), bounded
  geometric constraints                 minimum-thickness constraint
    (e.g. AIRFOIL_THICKNESS)
  adjoint gradients (all DVs for        in-process linear-vortex panel solver
    ~1 flow solve)                        (~10 ms/solve) -> cheap, noise-free
                                          finite-difference gradients
  SciPy SLSQP                           SciPy bounded trust-region least
                                          squares (same objective, uses its
                                          sum-of-squares structure)
  RANS/Euler flow solver                viscous XFOIL (stock binary) via a
                                          defect correction: the inviscid
                                          target is shifted by (viscous -
                                          inviscid) Cp of the current design
                                          and re-solved, 3-5 times

Everything runs on the standard XFOIL binary (XFOIL_PATH), not the old
patched xfoil_inverse; MDES/QDES, cp_to_qspec.py and gradient_design.py
are no longer used.

Why the old approach was replaced (measured, same targets, same metric):
it matched Cp at only 16 points with Gaussian bumps and a step-shrinking
Gauss-Newton loop, and stalled on 2 of 4 targets taken from real airfoils
(NACA 0008, NACA 6409: no verified result after ~106 s), where this
version recovers the true shape to ~0.1% chord in ~7 s.

Any seed airfoil can be used (fitted with CST first, fit error reported);
with no seed the default is NACA 0012.
"""

import math
import os
import platform
import subprocess
import time
from math import comb

import numpy as np
from scipy.optimize import least_squares

IS_WINDOWS = platform.system() == "Windows"
XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil.exe" if IS_WINDOWS else "xfoil")

N_SURF = 90                 # CST sample points per surface (cosine spaced)
CST_ORDERS = (8, 10, 12)    # tried in turn until the seed fits well enough
SEED_FIT_TOL = 5e-4         # max |dy|/c accepted for the seed fit
EDITOR_POINTS = 41          # points per surface in the frontend curve editor
MAX_CP = 1.0


# ─────────────────────────────────────────────────────────────────────────
# Linear-strength vortex panel method (Katz & Plotkin, VOR2DL), vectorised.
# Checked against XFOIL's inviscid solution on NACA 0012 / 4412 at 4 deg:
# mean |dCp| 0.007-0.013 away from the TE, CL within 0.5-1.7 %.
# ─────────────────────────────────────────────────────────────────────────

def panel_cp(xs, ys, alpha_deg):
    """Coordinates in Selig order (TE upper -> LE -> TE lower). Returns
    (xc, yc, cp) at panel midpoints, Selig order."""
    x = np.asarray(xs, float)[::-1]
    y = np.asarray(ys, float)[::-1]
    n = len(x) - 1
    a = math.radians(alpha_deg)
    th = np.arctan2(np.diff(y), np.diff(x))
    xc = 0.5 * (x[:-1] + x[1:])
    yc = 0.5 * (y[:-1] + y[1:])
    cj, sj = np.cos(th), np.sin(th)
    dx = xc[:, None] - x[None, :-1]
    dy = yc[:, None] - y[None, :-1]
    X = dx * cj[None, :] + dy * sj[None, :]
    Y = -dx * sj[None, :] + dy * cj[None, :]
    X2 = np.hypot(np.diff(x), np.diff(y))[None, :]
    eye = np.eye(n, dtype=bool)
    Y = np.where(eye, 0.0, Y)
    R1 = np.hypot(X, Y)
    R2 = np.hypot(X - X2, Y)
    dTH = np.arctan2(Y, X - X2) - np.arctan2(Y, X)
    with np.errstate(divide="ignore", invalid="ignore"):
        LN = np.where(eye, 0.0, np.log(R2 / R1))
    tp = 2 * np.pi * X2
    U1L = np.where(eye, -0.5 * (X - X2) / X2, -(Y * LN + X * dTH - X2 * dTH) / tp)
    U2L = np.where(eye, 0.5 * X / X2, (Y * LN + X * dTH) / tp)
    W1L = np.where(eye, -1 / (2 * np.pi), -((X2 - Y * dTH) + X * LN - X2 * LN) / tp)
    W2L = np.where(eye, 1 / (2 * np.pi), ((X2 - Y * dTH) + X * LN) / tp)
    U1, W1 = U1L * cj - W1L * sj, U1L * sj + W1L * cj
    U2, W2 = U2L * cj - W2L * sj, U2L * sj + W2L * cj
    ci, si = np.cos(th)[:, None], np.sin(th)[:, None]
    A = np.zeros((n + 1, n + 1))
    B = np.zeros((n, n + 1))
    A[:n, :n] += -U1 * si + W1 * ci
    A[:n, 1:] += -U2 * si + W2 * ci
    B[:, :n] += U1 * ci + W1 * si
    B[:, 1:] += U2 * ci + W2 * si
    A[n, 0] = A[n, n] = 1.0  # Kutta condition
    rhs = np.zeros(n + 1)
    rhs[:n] = math.cos(a) * np.sin(th) - math.sin(a) * np.cos(th)
    g = np.linalg.solve(A, rhs)
    vt = B @ g + math.cos(a) * np.cos(th) + math.sin(a) * np.sin(th)
    return xc[::-1], yc[::-1], (1.0 - vt ** 2)[::-1]


def pressure_cl(xs, ys, cp_mid, alpha_deg):
    """Lift coefficient from integrating panel-midpoint Cp (Selig order)."""
    dxp, dyp = np.diff(xs), np.diff(ys)
    fx = np.sum(cp_mid * dyp)
    fy = -np.sum(cp_mid * dxp)
    a = math.radians(alpha_deg)
    return -(fy * math.cos(a) - fx * math.sin(a))  # Selig order runs clockwise


# ─────────────────────────────────────────────────────────────────────────
# Geometry: seeds and CST parameterisation
# ─────────────────────────────────────────────────────────────────────────

def cosine_x(n):
    return 0.5 * (1 - np.cos(np.linspace(0, np.pi, n)))


def naca4(code="0012", n=200):
    m, p, t = int(code[0]) / 100, int(code[1]) / 10, int(code[2:]) / 100
    x = cosine_x(n)
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.126 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1036 * x**4)
    if m == 0:
        yc = np.zeros_like(x)
        dyc = np.zeros_like(x)
    else:
        yc = np.where(x < p, m / p**2 * (2 * p * x - x**2), m / (1 - p)**2 * ((1 - 2 * p) + 2 * p * x - x**2))
        dyc = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p)**2 * (p - x))
    th = np.arctan(dyc)
    xu, yu = x - yt * np.sin(th), yc + yt * np.cos(th)
    xl, yl = x + yt * np.sin(th), yc - yt * np.cos(th)
    return np.concatenate([xu[::-1], xl[1:]]), np.concatenate([yu[::-1], yl[1:]])


def default_seed():
    # 199 points: XFOIL 6.99's arrays (the Windows build) overflow with 399
    # ("Array size (IWX) too small") and then converge slowly to a wrong CD.
    x, y = naca4("0012", n=100)
    return np.c_[x, y]


def normalize_seed(coords):
    """Selig order, LE at (0,0), TE midpoint at (1,0), upper surface first."""
    c = np.asarray(coords, float)
    if len(c) < 10:
        raise ValueError("Seed airfoil needs at least 10 points")
    te = 0.5 * (c[0] + c[-1])
    ile = int(np.argmax(np.hypot(c[:, 0] - te[0], c[:, 1] - te[1])))
    le = c[ile]
    ang = math.atan2(te[1] - le[1], te[0] - le[0])
    chord = math.hypot(te[0] - le[0], te[1] - le[1])
    rot = np.array([[math.cos(-ang), -math.sin(-ang)], [math.sin(-ang), math.cos(-ang)]])
    c = ((c - le) @ rot.T) / chord
    # upper surface first
    if np.mean(c[:ile + 1, 1]) < np.mean(c[ile:, 1]):
        c = c[::-1]
        ile = len(c) - 1 - ile
    return c, ile


def _bern(x, n):
    return np.array([comb(n, i) * x ** i * (1 - x) ** (n - i) for i in range(n + 1)]).T


class CST:
    """Kulfan CST: y = sqrt(x)(1-x) * sum_i A_i B_i^n(x) + x * dz_te."""

    def __init__(self, order, dz_u=0.0, dz_l=0.0):
        self.n = order
        self.xs = cosine_x(N_SURF)
        self.B = _bern(self.xs, order)
        self.C = np.sqrt(self.xs) * (1 - self.xs)
        self.dz_u, self.dz_l = dz_u, dz_l
        self.nvar = 2 * (order + 1)

    def surfaces(self, p):
        k = self.n + 1
        yu = self.C * (self.B @ p[:k]) + self.xs * self.dz_u
        yl = self.C * (self.B @ p[k:]) + self.xs * self.dz_l
        return yu, yl

    def coords(self, p):
        yu, yl = self.surfaces(p)
        return (np.concatenate([self.xs[::-1], self.xs[1:]]),
                np.concatenate([yu[::-1], yl[1:]]))


def fit_seed(coords):
    """Fit a CST to an arbitrary seed. Returns (cst, params, max_fit_error)."""
    c, ile = normalize_seed(coords)
    up = c[:ile + 1][::-1]
    lo = c[ile:]
    up = up[np.argsort(up[:, 0])]
    lo = lo[np.argsort(lo[:, 0])]
    dz_u = float(np.interp(1.0, up[:, 0], up[:, 1]))
    dz_l = float(np.interp(1.0, lo[:, 0], lo[:, 1]))
    best = None
    for order in CST_ORDERS:
        cst = CST(order, dz_u, dz_l)
        params, err = [], 0.0
        for srf, dz in ((up, dz_u), (lo, dz_l)):
            m = (srf[:, 0] > 1e-5) & (srf[:, 0] < 1 - 1e-5)
            xx = np.clip(srf[m, 0], 0, 1)
            A = (np.sqrt(xx) * (1 - xx))[:, None] * _bern(xx, order)
            coef = np.linalg.lstsq(A, srf[m, 1] - xx * dz, rcond=None)[0]
            params.append(coef)
            err = max(err, float(np.max(np.abs(A @ coef + xx * dz - srf[m, 1]))))
        p = np.concatenate(params)
        if best is None or err < best[2]:
            best = (cst, p, err)
        if err <= SEED_FIT_TOL:
            break
    return best


# ─────────────────────────────────────────────────────────────────────────
# Target handling
# ─────────────────────────────────────────────────────────────────────────

def clean_target(points, name):
    arr = np.asarray(points, float)
    if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) < 3:
        raise ValueError(f"{name} needs at least 3 [x, Cp] points")
    arr = arr[np.argsort(arr[:, 0])]
    return arr


def target_cl_from_curve(tu, tl, alpha_deg):
    """Normal-force integral of the drawn curve, rotated to lift. This is
    what the drawn curve itself implies (no solver involved)."""
    x = np.linspace(0, 1, 2001)
    cn = np.trapezoid(np.interp(x, tl[:, 0], tl[:, 1]) - np.interp(x, tu[:, 0], tu[:, 1]), x)
    return float(cn * math.cos(math.radians(alpha_deg)))


def target_warnings(tu, tl):
    w = []
    if tu[:, 1].max() > MAX_CP + 1e-6 or tl[:, 1].max() > MAX_CP + 1e-6:
        w.append("The target has Cp above 1 somewhere. Cp can't exceed 1 (stagnation) in "
                 "incompressible flow, so those points were capped at 1.")
    te_gap = abs(float(tu[-1, 1]) - float(tl[-1, 1]))
    if te_gap > 0.1:
        w.append(f"Upper and lower target Cp differ by {te_gap:.2f} at the trailing edge. "
                 "Real flow leaves the trailing edge smoothly (equal pressure on both sides), "
                 "so the design can't match both there.")
    return w


# ─────────────────────────────────────────────────────────────────────────
# XFOIL (stock) viscous evaluation
# ─────────────────────────────────────────────────────────────────────────

def _parse_pacc(path):
    rows, started = [], False
    if not os.path.exists(path):
        return rows
    for line in open(path):
        if line.strip().startswith("------"):
            started = True
            continue
        parts = line.split()
        if started and len(parts) >= 5:
            try:
                rows.append([float(v) for v in parts[:5]])
            except ValueError:
                pass
    return rows


def _read_cpwr(path):
    """XFOIL's CPWR file as an (n, 2) array of [x, Cp], or None.
    XFOIL 6.97 (Debian/Render) writes one '#  x  Cp' header and two columns;
    6.99 (the Windows build) adds a name line and an 'Alfa = ...' line
    without '#', and an extra y column (x, y, Cp). Cp is always the last
    column, and only all-numeric lines are data."""
    rows = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    vals = [float(v) for v in parts]
                except ValueError:
                    continue  # header / name / "Alfa = ..." line
                rows.append((vals[0], vals[-1]))
    except OSError:
        return None
    return np.array(rows) if len(rows) >= 10 else None


def xfoil_viscous(x, y, reynolds, alpha, ncrit, work_dir, tag, timeout=60):
    """Viscous XFOIL on the given coordinates. Tries the design's own
    paneling (PCOP) first, then XFOIL's repaneling (PANE), then an alpha
    ramp. Returns dict(ok, CL, CD, CM, upper, lower) with upper/lower as
    (x, cp) arrays sorted by x, or ok=False."""
    geo = f"geo_{tag}.dat"
    with open(os.path.join(work_dir, geo), "w", newline="\n") as f:
        f.write("DESIGN\n")
        for xi, yi in zip(x, y):
            f.write(f"{xi:.7f} {yi:.7f}\n")

    attempts = [("PCOP", [f"ALFA {alpha}"]),
                ("PANE", [f"ALFA {alpha}"])]
    if len(x) > 300:
        # Too many points to use as panels directly in XFOIL 6.99: let XFOIL
        # repanel first (PCOP is still tried, as a fallback).
        attempts.reverse()
    if abs(alpha) > 1.0:
        step = 1.0 if alpha > 0 else -1.0
        attempts.append(("PANE", [f"ASEQ 0 {alpha - step} {step}", f"ALFA {alpha}"]))

    env = os.environ.copy()
    if not IS_WINDOWS and "DISPLAY" not in env:
        env["DISPLAY"] = ":99"

    for k, (pan, oper) in enumerate(attempts):
        pol, cpf = f"pol_{tag}_{k}.dat", f"cp_{tag}_{k}.dat"
        for fn in (pol, cpf):
            if os.path.exists(os.path.join(work_dir, fn)):
                os.remove(os.path.join(work_dir, fn))
        script = ["PLOP", "G", "", f"LOAD {geo}", pan, "OPER",
                  f"VISC {int(reynolds)}", "ITER 200", "VPAR", f"N {ncrit}", "",
                  "PACC", pol, ""] + oper + ["PACC", f"CPWR {cpf}", "", "QUIT"]
        path = os.path.join(work_dir, f"script_{tag}_{k}.txt")
        with open(path, "w", newline="\n") as f:
            f.write("\n".join(script) + "\n")
        try:
            with open(path) as sf:
                subprocess.run([XFOIL_EXE], stdin=sf, capture_output=True, text=True,
                               cwd=work_dir, env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            continue
        rows = [r for r in _parse_pacc(os.path.join(work_dir, pol)) if abs(r[0] - alpha) < 1e-3]
        cp_path = os.path.join(work_dir, cpf)
        if not rows or not os.path.exists(cp_path):
            continue
        cp = _read_cpwr(cp_path)
        if cp is None:
            continue
        if not np.all(np.isfinite(cp)) or np.abs(cp[:, 1]).max() > 20:
            continue
        ile = int(np.argmin(cp[:, 0]))
        up = cp[:ile + 1][::-1]
        lo = cp[ile:]
        _, cl, cd, _, cm = rows[-1]
        return {"ok": True, "CL": cl, "CD": cd, "CM": cm,
                "upper": up[np.argsort(up[:, 0])], "lower": lo[np.argsort(lo[:, 0])],
                "method": pan if len(oper) == 1 else "PANE+ramp"}
    return {"ok": False}


# ─────────────────────────────────────────────────────────────────────────
# The optimisation
# ─────────────────────────────────────────────────────────────────────────

def _panel_split(cst):
    """Index of the first lower-surface panel in Selig order."""
    return N_SURF - 1


def _on_panels(cst, xc, curves):
    """Evaluate (upper, lower) x-sorted curves at panel midpoints."""
    n_up = _panel_split(cst)
    out = np.empty(len(xc))
    out[:n_up] = np.interp(xc[:n_up], curves[0][:, 0], curves[0][:, 1])
    out[n_up:] = np.interp(xc[n_up:], curves[1][:, 0], curves[1][:, 1])
    return out


def _thickness_limit(xs):
    """Local thickness floor so the surfaces never cross: 0.2 % chord at
    mid-chord, tapering to zero at the LE and TE."""
    return 0.002 * 4 * xs * (1 - xs)


def _lift_gap_region(xc, L, err, n_up, width=0.1):
    """Where along the chord the viscous Cp error contributes most to the
    lift difference (error integrated over 10%-chord bins)."""
    best = (0.0, "", 0.0)
    for name, sl, sign in (("upper", slice(0, n_up), -1.0), ("lower", slice(n_up, None), 1.0)):
        x, dl, e = xc[sl], L[sl], err[sl]
        for a in np.arange(0.0, 1.0, width):
            m = (x >= a) & (x < a + width)
            contrib = float(np.sum(sign * e[m] * dl[m]))
            if abs(contrib) > abs(best[0]):
                best = (contrib, name, a)
    _, name, a = best
    return f"the {name} surface between x/c = {a:.1f} and {a + width:.1f}"


def run_inverse_design(work_dir, reynolds, alpha, target_cp_upper, target_cp_lower,
                       seed_coords=None, ncrit=9.0, min_thickness=0.0,
                       n_viscous=6, max_seconds=90.0, regularization=1e-3, progress=None):
    """
    Returns a JSON-ready dict (see keys at the bottom). min_thickness is a
    fraction of chord (0 = no constraint beyond "surfaces can't cross").
    progress: optional callback(fraction 0..1, message) reporting the real
    stage of the run (used for the progress bar on the web page).
    """
    t_start = time.time()
    total_steps = 4 + n_viscous   # fit, seed check, inviscid match, first viscous check, corrections

    def report(done, message):
        if progress is not None:
            try:
                progress(min(1.0, done / total_steps), message)
            except Exception:
                pass

    report(0, "Fitting the seed shape")
    warnings = []
    tu = clean_target(target_cp_upper, "target_cp_upper")
    tl = clean_target(target_cp_lower, "target_cp_lower")
    warnings += target_warnings(tu, tl)
    tu[:, 1] = np.minimum(tu[:, 1], MAX_CP)
    tl[:, 1] = np.minimum(tl[:, 1], MAX_CP)

    if seed_coords is None:
        seed_coords = default_seed()
        seed_name = "NACA 0012 (default)"
    else:
        seed_name = "uploaded seed"
    cst, p0, fit_err = fit_seed(np.asarray(seed_coords, float).reshape(-1, 2))
    if fit_err > 5e-3:
        warnings.append(f"The seed airfoil could only be approximated to {fit_err*100:.2f}% chord by the "
                        "smooth shape functions used for design (sharp kinks or noisy points).")

    x0, y0 = cst.coords(p0)
    xc0, _, _ = panel_cp(x0, y0, alpha)
    L = np.hypot(np.diff(x0), np.diff(y0))
    target_panels = _on_panels(cst, xc0, (tu, tl))
    t_floor = _thickness_limit(cst.xs)

    def residuals(p, tgt):
        x, y = cst.coords(p)
        _, _, cp = panel_cp(x, y, alpha)
        r = np.sqrt(L) * (tgt - cp)
        yu, yl = cst.surfaces(p)
        th = yu - yl
        pen = [10.0 * np.maximum(0.0, t_floor - th)[1:-1]]
        if min_thickness > 0:
            pen.append(np.atleast_1d(100.0 * max(0.0, min_thickness - float(th.max()))))
        return np.concatenate([r] + pen + [regularization * (p - p0)])

    bounds = (p0 - 0.5, p0 + 0.5)
    history = []
    report(1, "Checking the seed airfoil in XFOIL")
    seed_eval = xfoil_viscous(x0, y0, reynolds, alpha, ncrit, work_dir, "seed")

    def solve_inviscid(start, tgt):
        sol = least_squares(residuals, start, args=(tgt,), bounds=bounds, method="trf",
                            x_scale=0.02, diff_step=1e-4, max_nfev=80)
        return sol.x

    def evaluate(p, tag):
        """Viscous state of design p: (rms vs target, visc, cp_inv, err) or None."""
        x, y = cst.coords(p)
        xc, _, cp_inv = panel_cp(x, y, alpha)
        visc = xfoil_viscous(x, y, reynolds, alpha, ncrit, work_dir, tag)
        if not visc["ok"]:
            return None
        cp_visc = _on_panels(cst, xc, (visc["upper"], visc["lower"]))
        err = target_panels - cp_visc
        return {"rms": float(np.sqrt(np.sum(L * err ** 2) / L.sum())), "visc": visc,
                "cp_inv": cp_inv, "cp_visc": cp_visc, "err": err, "p": p}

    # Step 0: pure inviscid match of the target (the SU2-style optimisation)
    report(2, "Matching the target pressure distribution")
    p = solve_inviscid(p0.copy(), target_panels)
    report(3, "Checking the first design in viscous XFOIL")
    state = evaluate(p, "it0")
    history.append({"iteration": 0, "viscous_converged": state is not None,
                    **({"viscous_rms": state["rms"], "CL": state["visc"]["CL"]} if state else {})})
    best = dict(state, iteration=0) if state else {"p": p, "visc": None, "rms": None, "err": None, "iteration": 0}

    # Viscous correction, monotone: shift the inviscid target by the current
    # viscous-minus-inviscid defect, re-solve, then line-search between the
    # current design and the new one, accepting only a step that actually
    # lowers the VISCOUS Cp error. (A plain defect-correction loop was tried
    # first and oscillated on laminar-bubble-sensitive targets, e.g. rooftop
    # distributions at Re 5e5: rms 0.055 -> 0.117 -> 0.099.)
    it = 0
    while state is not None and it < n_viscous:
        if time.time() - t_start > max_seconds:
            warnings.append("Stopped the viscous refinement early to stay within the time limit.")
            break
        it += 1
        report(3 + it, f"Viscous correction {it} of up to {n_viscous}")
        tgt_inv = target_panels - (state["cp_visc"] - state["cp_inv"])
        cand = solve_inviscid(state["p"], tgt_inv)
        accepted = None
        for k, step in enumerate((1.0, 0.5, 0.25)):
            trial = evaluate(state["p"] + step * (cand - state["p"]), f"it{it}_{k}")
            if trial is not None and trial["rms"] < state["rms"] * 0.995:
                accepted = trial
                break
        if accepted is None:
            break  # no step lowers the viscous error any further
        state = accepted
        history.append({"iteration": it, "viscous_converged": True, "viscous_rms": state["rms"],
                        "CL": state["visc"]["CL"], "step": step})
        if state["rms"] < best["rms"]:
            best = dict(state, iteration=it)
        if state["rms"] < 0.005:
            break

    report(total_steps, "Finishing")
    p_best = best["p"]
    x, y = cst.coords(p_best)
    xc, _, cp_inv_best = panel_cp(x, y, alpha)
    yu, yl = cst.surfaces(p_best)
    th = yu - yl
    yu0, yl0 = cst.surfaces(p0)
    th0 = yu0 - yl0
    visc = best["visc"]
    verified = visc is not None

    n_up = _panel_split(cst)
    per_surface = None
    if verified:
        e = best["err"]
        per_surface = {
            "upper_rms": float(np.sqrt(np.sum(L[:n_up] * e[:n_up] ** 2) / L[:n_up].sum())),
            "lower_rms": float(np.sqrt(np.sum(L[n_up:] * e[n_up:] ** 2) / L[n_up:].sum())),
            "max_abs_error": float(np.max(np.abs(e))),
            "x_of_max_error": float(xc[int(np.argmax(np.abs(e)))]),
        }
        target_cl = target_cl_from_curve(tu, tl, alpha)
        if abs(target_cl) > 0.05 and abs(visc["CL"] - target_cl) > 0.1 * abs(target_cl):
            warnings.append(
                f"The designed airfoil makes CL = {visc['CL']:.3f}, {abs(visc['CL'] - target_cl) / abs(target_cl) * 100:.0f}% "
                f"{'below' if visc['CL'] < target_cl else 'above'} the {target_cl:.3f} your curve implies. Most of "
                f"the lift difference comes from {_lift_gap_region(xc, L, best['err'], n_up)}. Usually this means part of "
                "the target can't happen in real viscous flow, most often a pressure recovery too steep for the "
                "boundary layer, which then separates.")
    else:
        warnings.append("XFOIL's viscous analysis didn't converge on the designed shape, so the "
                        "result below is the inviscid design only (not viscous-verified).")

    return {
        "verification_succeeded": verified,
        "seed_name": seed_name,
        "seed_fit_error": fit_err,
        "target_cl": target_cl_from_curve(tu, tl, alpha),
        "coefficients": ({"CL": visc["CL"], "CD": visc["CD"], "CM": visc["CM"]} if verified else None),
        "inviscid_cl": float(pressure_cl(x, y, cp_inv_best, alpha)),
        "seed_coefficients": ({"CL": seed_eval["CL"], "CD": seed_eval["CD"], "CM": seed_eval["CM"]}
                              if seed_eval.get("ok") else None),
        "fit": {"viscous_rms": best["rms"], **(per_surface or {})},
        "new_coords": np.c_[x, y].tolist(),
        "seed_coords": np.c_[x0, y0].tolist(),
        "max_thickness": float(th.max()), "max_thickness_x": float(cst.xs[int(np.argmax(th))]),
        "seed_max_thickness": float(th0.max()),
        "result_cp_upper": visc["upper"].tolist() if verified else None,
        "result_cp_lower": visc["lower"].tolist() if verified else None,
        "target_cp_upper": tu.tolist(), "target_cp_lower": tl.tolist(),
        "history": history,
        "best_iteration": best["iteration"],
        "warnings": warnings,
        "elapsed_seconds": time.time() - t_start,
    }


def seed_baseline(work_dir, reynolds, alpha, seed_coords=None, ncrit=9.0):
    """Cp of the seed (viscous XFOIL, inviscid panel fallback) sampled at
    the curve editor's points, so drawing starts from the seed's own
    pressure distribution at the chosen condition."""
    if seed_coords is None:
        seed_coords = default_seed()
    c, ile = normalize_seed(np.asarray(seed_coords, float).reshape(-1, 2))
    xe = cosine_x(EDITOR_POINTS)
    visc = xfoil_viscous(c[:, 0], c[:, 1], reynolds, alpha, ncrit, work_dir, "baseline")
    if visc["ok"]:
        up, lo, source, cl = visc["upper"], visc["lower"], "xfoil_viscous", visc["CL"]
    else:
        xc, _, cp = panel_cp(c[:, 0], c[:, 1], alpha)
        k = int(np.argmin(xc))
        up = np.c_[xc[:k + 1], cp[:k + 1]][::-1]
        lo = np.c_[xc[k:], cp[k:]]
        up, lo = up[np.argsort(up[:, 0])], lo[np.argsort(lo[:, 0])]
        source, cl = "panel_inviscid", float(pressure_cl(c[:, 0], c[:, 1], cp, alpha))
    cu = np.interp(xe, up[:, 0], up[:, 1])
    cl_ = np.interp(xe, lo[:, 0], lo[:, 1])
    # shared LE/TE points (the editor links them)
    le = float(max(cu[0], cl_[0]))
    te = float(0.5 * (cu[-1] + cl_[-1]))
    cu[0] = cl_[0] = min(le, MAX_CP)
    cu[-1] = cl_[-1] = te
    return {"x": xe.round(4).tolist(), "upper": np.round(cu, 4).tolist(),
            "lower": np.round(cl_, 4).tolist(), "source": source, "CL": cl,
            "seed_coords": c.tolist()}


def run_inverse_design_job(queue, args, kwargs):
    """Entry point when main.py runs a design in a separate process.

    Running it in its own process (at lower CPU priority) means a design
    can't starve the web server of CPU, and a cancelled design can simply be
    killed. Progress, the result or the error go back through `queue` as
    ("progress", fraction, message), ("done", result), ("value_error", text)
    or ("error", text).
    """
    try:
        if hasattr(os, "setpgrp"):
            os.setpgrp()    # own process group, so the XFOIL runs it starts die with it
        if hasattr(os, "nice"):
            os.nice(10)     # lower priority than the web server and normal analyses
    except Exception:
        pass
    try:
        result = run_inverse_design(*args, **kwargs,
                                    progress=lambda f, m: queue.put(("progress", f, m)))
        queue.put(("done", result))
    except ValueError as e:
        queue.put(("value_error", str(e)))
    except Exception as e:
        queue.put(("error", str(e) or type(e).__name__))
