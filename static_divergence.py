"""
static_divergence.py
=====================

Module 1 of the aeroelasticity feature: static torsional divergence of a
rigid airfoil section on a torsional spring (the "typical section",
torsion-only). Also hosts the shared XFOIL polar layer used by
control_reversal.py and flutter_vg.py.

Physics
-------
A rigid section at root angle alpha_root sits on a torsional spring of
stiffness k_alpha about an elastic axis at x_EA/c. At dynamic pressure q
the aerodynamic moment about the elastic axis twists it by theta:

    k_alpha * theta = q * S * c * Cm_EA(alpha_root + theta)
    Cm_EA = Cm_c4 + Cl * (x_EA/c - 0.25)          (nose-up positive)
    S = c * span

Divergence is the fold (saddle-node) of this equilibrium: the point where
the effective torsional stiffness

    K_eff = k_alpha - q * S * c * dCm_EA/dalpha        (dalpha in rad)

reaches zero. Past it the equilibrium the wing was sitting on no longer
exists and the twist runs away.

How it's solved (rebuilt 2026-09)
---------------------------------
The equilibrium is solved *backwards*: for each twist theta, the dynamic
pressure that holds it there is explicit,

    q(theta) = k_alpha * theta / (S * c * Cm_EA(alpha_root + theta)),

so the whole equilibrium branch is traced exactly on a fine theta grid
with no root-finding at all, and divergence is simply the first local
maximum of q(theta) -- which is exactly K_eff = 0, since
dq/dtheta = K_eff / (S * c * Cm_EA).

Cl(alpha) and Cm(alpha) come from ONE viscous XFOIL polar sweep (ASEQ)
read from XFOIL's PACC polar file, which only records converged points,
then interpolated (PCHIP, no overshoot).

This replaced an earlier version that
  (a) parsed the FIRST "CL =" line of XFOIL's console output -- the first
      viscous iteration, not the converged answer (NACA 0012 at 16.9 deg,
      Re 5e5: read CL=2.37 / Cm=-0.150, converged is CL=1.14 / Cm=+0.014),
  (b) root-found each airspeed separately with widening warm-start
      windows, which could hop onto an unrelated root after the real
      branch folded -- with the UI defaults it reported "no divergence"
      although the twist jumped 2.8 -> 7.9 deg at ~62 m/s, and
  (c) needed ~2,000 XFOIL calls (~135 s) per run.

Uses the standard XFOIL binary (XFOIL_PATH, as main.py), not the patched
inverse-design binary.

Linear cross-check (textbook typical section, e.g. Bisplinghoff/Hodges &
Pierce):  q_div = k_alpha / (S * c * e * a0),  e = x_EA/c - x_AC/c,
with a0 and x_AC measured from the same polar at alpha_root.
"""

import math
import os
import platform
import subprocess

import numpy as np
from scipy.interpolate import PchipInterpolator


# ─────────────────────────────────────────────────────────────────────────
# XFOIL polar layer (shared by all three modules)
# ─────────────────────────────────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"
XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil.exe" if IS_WINDOWS else "xfoil")

DEFAULT_ALPHA_MIN = -10.0
DEFAULT_ALPHA_MAX = 20.0
DEFAULT_ALPHA_STEP = 0.5

# If the effective stiffness K_eff drops below this fraction of k_alpha
# without a strict fold, the twist is running away and only stall stops it.
RUNAWAY_STIFFNESS_RATIO = 0.15


class XfoilPolarError(RuntimeError):
    """XFOIL did not produce a usable polar."""


def _run_xfoil(script_lines, work_dir, script_name, timeout):
    script_path = os.path.join(work_dir, script_name)
    with open(script_path, "w", newline="\n") as f:
        f.write("\n".join(script_lines) + "\n")

    env = os.environ.copy()
    if not IS_WINDOWS and "DISPLAY" not in env:
        env["DISPLAY"] = ":99"

    with open(script_path, "r") as script_file:
        proc = subprocess.Popen(
            [XFOIL_EXE],
            stdin=script_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=work_dir,
            env=env,
        )
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise XfoilPolarError(f"XFOIL timed out after {timeout}s")
    return stdout


def _parse_pacc(path):
    """Rows (alpha, cl, cd, cm) from an XFOIL PACC polar file. XFOIL only
    writes a row here when the viscous solution converged."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r") as f:
        lines = f.readlines()
    started = False
    for line in lines:
        if not started:
            if line.strip().startswith("------"):
                started = True
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            alpha, cl, cd, _cdp, cm = (float(p) for p in parts[:5])
        except ValueError:
            continue
        rows.append((alpha, cl, cd, cm))
    return rows


def _clean_rows(rows, alpha_step):
    """Sort, de-duplicate and drop isolated spikes (XFOIL occasionally
    'converges' onto a nonsense solution for a single point)."""
    by_alpha = {}
    for a, cl, cd, cm in rows:
        by_alpha[round(a, 4)] = (a, cl, cd, cm)
    pts = [by_alpha[k] for k in sorted(by_alpha)]
    if len(pts) < 3:
        return pts
    keep = [True] * len(pts)
    for i in range(1, len(pts) - 1):
        a0, cl0 = pts[i - 1][0], pts[i - 1][1]
        a1, cl1 = pts[i][0], pts[i][1]
        a2, cl2 = pts[i + 1][0], pts[i + 1][1]
        if a2 - a0 > 3 * alpha_step:
            continue
        expected = cl0 + (cl2 - cl0) * (a1 - a0) / (a2 - a0)
        if abs(cl1 - expected) > 0.2 and abs(cl2 - cl0) < 0.2:
            keep[i] = False
    return [p for p, k in zip(pts, keep) if k]


class Polar:
    """Converged XFOIL polar with monotone (PCHIP) interpolation."""

    def __init__(self, alpha, cl, cm, cd, label="base"):
        self.alpha = np.asarray(alpha, float)
        self.cl_data = np.asarray(cl, float)
        self.cm_data = np.asarray(cm, float)
        self.cd_data = np.asarray(cd, float)
        self.label = label
        self.alpha_min = float(self.alpha[0])
        self.alpha_max = float(self.alpha[-1])
        self._cl = PchipInterpolator(self.alpha, self.cl_data, extrapolate=False)
        self._cm = PchipInterpolator(self.alpha, self.cm_data, extrapolate=False)
        i_max = int(np.argmax(self.cl_data))
        i_min = int(np.argmin(self.cl_data))
        # Only call it "stall" if Cl actually turns over inside the range
        self.stall_alpha_pos = float(self.alpha[i_max]) if i_max < len(self.alpha) - 1 else None
        self.stall_alpha_neg = float(self.alpha[i_min]) if i_min > 0 else None

    def contains(self, a):
        return self.alpha_min <= a <= self.alpha_max

    def cl(self, a):
        return self._cl(a)

    def cm(self, a):
        return self._cm(a)

    def local_slopes(self, a, half_window=1.0):
        """Least-squares dCl/dalpha, dCm/dalpha (per DEGREE) from the raw
        polar points within +/- half_window deg of a -- more robust to
        XFOIL point-to-point noise than differentiating the interpolant."""
        mask = np.abs(self.alpha - a) <= half_window + 1e-9
        if mask.sum() < 3:
            order = np.argsort(np.abs(self.alpha - a))[:3]
            mask = np.zeros_like(mask)
            mask[order] = True
        A = np.vstack([self.alpha[mask], np.ones(mask.sum())]).T
        dcl = float(np.linalg.lstsq(A, self.cl_data[mask], rcond=None)[0][0])
        dcm = float(np.linalg.lstsq(A, self.cm_data[mask], rcond=None)[0][0])
        return dcl, dcm

    def aero_params(self, a):
        """Lift-curve slope (per rad) and aerodynamic-centre location at a."""
        dcl, dcm = self.local_slopes(a)
        a0 = dcl * 180.0 / math.pi
        x_ac = 0.25 - (dcm / dcl if dcl != 0 else 0.0)
        return {"a0_per_rad": a0, "x_ac_over_c": x_ac}

    def to_dict(self):
        return {
            "alpha": self.alpha.tolist(),
            "cl": self.cl_data.tolist(),
            "cm": self.cm_data.tolist(),
            "cd": self.cd_data.tolist(),
            "stall_alpha_pos": self.stall_alpha_pos,
            "stall_alpha_neg": self.stall_alpha_neg,
        }


def _load_lines(seed_filename):
    return [f"LOAD {seed_filename}"] if seed_filename else ["NACA 0012"]


def run_polar(work_dir, seed_filename, reynolds, ncrit,
              alpha_min=DEFAULT_ALPHA_MIN, alpha_max=DEFAULT_ALPHA_MAX,
              alpha_step=DEFAULT_ALPHA_STEP, anchor_alpha=0.0,
              flap=None, tag="base", timeout=180):
    """
    One viscous XFOIL polar, swept outward from anchor_alpha in both
    directions (each sweep warm-starts from the previous point, which is
    how XFOIL converges best), returned as a Polar.

    flap: None, or (flap_chord_fraction, deflection_deg) -- applied with
    XFOIL's own GDES FLAP (hinge at mid-thickness) before paneling.
    """
    polar_name = f"polar_{tag}.txt"
    polar_path = os.path.join(work_dir, polar_name)
    if os.path.exists(polar_path):
        os.remove(polar_path)

    anchor = max(alpha_min, min(alpha_max, round(anchor_alpha / alpha_step) * alpha_step))

    lines = ["PLOP", "G", ""]  # disable graphics (avoids a hang on Windows)
    lines += _load_lines(seed_filename)
    if flap is not None:
        flap_frac, delta = flap
        lines += ["GDES", "FLAP", f"{1.0 - flap_frac:.4f}", "999", "0.5",
                  f"{delta:.4f}", "EXEC", ""]
    lines += [
        "PANE",
        "OPER",
        f"VISC {int(reynolds)}",
        "ITER 150",
        "VPAR", f"N {ncrit}", "",
        "PACC", polar_name, "",
    ]
    if anchor < alpha_max:
        lines.append(f"ASEQ {anchor} {alpha_max} {alpha_step}")
    else:
        lines.append(f"ALFA {anchor}")
    if anchor > alpha_min:
        lines += ["INIT", f"ASEQ {anchor - alpha_step} {alpha_min} {-alpha_step}"]
    lines += ["PACC", "", "QUIT"]

    stdout = _run_xfoil(lines, work_dir, f"script_{tag}.txt", timeout)
    rows = _clean_rows(_parse_pacc(polar_path), alpha_step)

    # Keep only the contiguous block around the anchor -- never interpolate
    # across a big hole where XFOIL failed to converge.
    if rows:
        alphas = [r[0] for r in rows]
        i0 = int(np.argmin([abs(a - anchor) for a in alphas]))
        gap = 3.5 * alpha_step
        lo = i0
        while lo > 0 and alphas[lo] - alphas[lo - 1] <= gap:
            lo -= 1
        hi = i0
        while hi < len(rows) - 1 and alphas[hi + 1] - alphas[hi] <= gap:
            hi += 1
        rows = rows[lo:hi + 1]

    if len(rows) < 5:
        tail = stdout[-400:] if stdout else ""
        raise XfoilPolarError(
            f"XFOIL converged at only {len(rows)} angles for the {tag} polar "
            f"(Re={reynolds:.0f}). Try a different Reynolds number or airfoil. "
            f"Last XFOIL output: {tail}"
        )

    a, cl, cd, cm = (list(col) for col in zip(*rows))
    return Polar(a, cl, cm, cd, label=tag)


def forward_cl_cm(work_dir, seed_filename, reynolds, alpha, ncrit, timeout=60):
    """Single-angle converged (CL, Cm_c4). Kept for backwards
    compatibility; reads the PACC row, so it only ever returns a
    converged viscous answer and raises otherwise."""
    polar_name = "polar_single.txt"
    polar_path = os.path.join(work_dir, polar_name)
    if os.path.exists(polar_path):
        os.remove(polar_path)
    lines = ["PLOP", "G", ""] + _load_lines(seed_filename) + [
        "PANE", "OPER", f"VISC {int(reynolds)}", "ITER 200",
        "VPAR", f"N {ncrit}", "",
        "PACC", polar_name, "",
        f"ALFA {alpha}",
        "PACC", "", "QUIT",
    ]
    _run_xfoil(lines, work_dir, "script_single.txt", timeout)
    rows = _parse_pacc(polar_path)
    if not rows:
        raise RuntimeError(f"XFOIL did not converge at alpha={alpha}")
    _, cl, _, cm = rows[-1]
    return cl, cm


# ─────────────────────────────────────────────────────────────────────────
# Equilibrium branch (shared with control_reversal.py)
# ─────────────────────────────────────────────────────────────────────────

def cm_ea_functions(polar, x_ea_over_c):
    """Cm about the elastic axis and its alpha-derivative (per RAD)."""
    arm = x_ea_over_c - 0.25
    dcl = polar._cl.derivative()
    dcm = polar._cm.derivative()

    def cm_ea(a):
        return polar.cm(a) + polar.cl(a) * arm

    def dcm_ea_rad(a):
        return (dcm(a) + dcl(a) * arm) * 180.0 / math.pi

    return cm_ea, dcm_ea_rad


def trace_equilibrium_branch(polar, alpha_root, k_alpha, x_ea_over_c, chord, span,
                             dtheta_deg=0.01):
    """
    Traces the physical equilibrium branch starting at zero twist, using
    q(theta) = k*theta / (S*c*Cm_EA). Returns a dict of numpy arrays along
    the branch (theta_deg, alpha_deg, q, k_eff) up to whichever comes
    first: the divergence fold, the edge of the polar, or the twist
    saturating (Cm_EA -> 0, i.e. q -> infinity, no divergence possible).
    """
    if not polar.contains(alpha_root):
        raise XfoilPolarError(
            f"Root angle {alpha_root} deg is outside the converged XFOIL polar "
            f"range [{polar.alpha_min:.1f}, {polar.alpha_max:.1f}] deg."
        )
    S = chord * span
    cm_ea, dcm_ea_rad = cm_ea_functions(polar, x_ea_over_c)
    cm0 = float(cm_ea(alpha_root))
    if abs(cm0) > 1e-7:
        direction = 1.0 if cm0 > 0 else -1.0
    else:
        slope = float(dcm_ea_rad(alpha_root))
        direction = 1.0 if slope >= 0 else -1.0

    room = (polar.alpha_max - alpha_root) if direction > 0 else (alpha_root - polar.alpha_min)
    n = max(int(room / dtheta_deg), 2)
    theta = direction * np.linspace(dtheta_deg * 0.1, room, n)
    alpha = alpha_root + theta
    cmv = cm_ea(alpha)
    with np.errstate(divide="ignore", invalid="ignore"):
        q = k_alpha * np.radians(theta) / (S * chord * cmv)
    k_eff = k_alpha - q * S * chord * dcm_ea_rad(alpha)

    # Branch valid while q is finite and positive
    bad = ~np.isfinite(q) | (q <= 0)
    end = int(np.argmax(bad)) if bad.any() else len(q)
    saturates = bool(bad.any())
    theta, alpha, q, k_eff = theta[:end], alpha[:end], q[:end], k_eff[:end]

    fold_index = None
    dq = np.diff(q)
    down = np.where(dq <= 0)[0]
    if len(down):
        fold_index = int(down[0])
        # Refine the fold location: K_eff is linear-ish near the fold
        cut = fold_index + 1
        theta, alpha, q, k_eff = theta[:cut], alpha[:cut], q[:cut], k_eff[:cut]

    return {
        "theta_deg": theta, "alpha_deg": alpha, "q": q, "k_eff": k_eff,
        "direction": direction,
        "folded": fold_index is not None,
        "saturates": saturates and fold_index is None,
        "hit_polar_edge": (fold_index is None and not saturates),
    }


def _interp_on_branch(branch, q_target, key):
    q = branch["q"]
    if len(q) == 0 or q_target > q[-1]:
        return None
    if q_target <= q[0]:
        # below the first traced point: linear from zero twist
        return float(branch[key][0] * q_target / q[0]) if key == "theta_deg" else float(branch[key][0])
    return float(np.interp(q_target, q, branch[key]))


def _speed_grid(v_start, v_step, v_max):
    v_start = max(v_start, 0.1)
    v_step = max(v_step, 0.01)
    n = int(math.floor((v_max - v_start) / v_step + 1e-9)) + 1
    grid = [v_start + i * v_step for i in range(max(n, 1))]
    if grid[-1] < v_max - 1e-9:
        grid.append(v_max)
    return grid


def linear_divergence(polar, alpha_root, k_alpha, x_ea_over_c, chord, span, rho):
    p = polar.aero_params(alpha_root)
    e = x_ea_over_c - p["x_ac_over_c"]
    out = {"a0_per_rad": p["a0_per_rad"], "x_ac_over_c": p["x_ac_over_c"], "e_over_c": e,
           "q_div": None, "v_div": None}
    if e > 0 and p["a0_per_rad"] > 0:
        q = k_alpha / (chord * span * chord * e * p["a0_per_rad"])
        out["q_div"] = q
        out["v_div"] = math.sqrt(2 * q / rho)
    return out


# ─────────────────────────────────────────────────────────────────────────
# Divergence analysis
# ─────────────────────────────────────────────────────────────────────────

def divergence_from_polar(polar, alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                          v_start=5.0, v_step=2.0, v_max=150.0):
    """Pure-Python divergence analysis on an existing polar (no XFOIL)."""
    S = chord * span
    warnings = []
    linear = linear_divergence(polar, alpha_root, k_alpha, x_ea_over_c, chord, span, rho)
    branch = trace_equilibrium_branch(polar, alpha_root, k_alpha, x_ea_over_c, chord, span)
    q_max = 0.5 * rho * v_max ** 2

    if linear["e_over_c"] <= 0:
        warnings.append(
            f"The elastic axis ({x_ea_over_c*100:.1f}% chord) is at or ahead of the "
            f"aerodynamic centre ({linear['x_ac_over_c']*100:.1f}% chord), so lift twists "
            f"the section nose-down and torsional divergence cannot occur."
        )

    q_div = v_div = theta_div = alpha_div = None
    if branch["folded"]:
        q_div = float(branch["q"][-1])
        theta_div = float(branch["theta_deg"][-1])
        alpha_div = float(branch["alpha_deg"][-1])
        v_div = math.sqrt(2 * q_div / rho)

    # Minimum effective stiffness actually reached within the swept range --
    # reported always, and used to catch "stall-limited" divergence below.
    within = branch["q"] <= q_max
    k_min_ratio = v_k_min = None
    i_min = None
    if within.any():
        ratios = branch["k_eff"][within] / k_alpha
        i_min = int(np.argmin(ratios))
        k_min_ratio = float(ratios[i_min])
        v_k_min = math.sqrt(2 * float(branch["q"][within][i_min]) / rho)

    if q_div is not None and q_div <= q_max:
        stopped_reason = "divergence_found"
    elif (k_min_ratio is not None and k_min_ratio < RUNAWAY_STIFFNESS_RATIO
          and i_min < int(within.sum()) - 1):
        # No mathematical fold, but the effective stiffness collapsed to a
        # few percent of the structural value before the Cl/Cm curves
        # flattened and stiffened it again (stall, or XFOIL's laminar-bubble
        # kinks at low Re): the twist runs away over a few m/s. That IS
        # divergence in practice -- a real wing would not survive it.
        # Found on NACA 0012, Re 5e5, UI defaults: K_eff bottoms at 8% of
        # k_alpha at 61.8 m/s and the twist goes 2.8 -> 12 deg in 9 m/s.
        stopped_reason = "stall_limited_divergence"
        q_div = float(branch["q"][within][i_min])
        theta_div = float(branch["theta_deg"][within][i_min])
        alpha_div = float(branch["alpha_deg"][within][i_min])
        v_div = v_k_min
        th_before = _interp_on_branch(branch, 0.5 * rho * (0.93 * v_div) ** 2, "theta_deg")
        th_after = _interp_on_branch(branch, min(0.5 * rho * (1.07 * v_div) ** 2, float(branch["q"][-1])), "theta_deg")
        warnings.append(
            f"No strict mathematical divergence: the effective torsional stiffness "
            f"falls to {k_min_ratio*100:.0f}% of the structural value at {v_div:.1f} m/s, "
            f"where the twist runs away (about {th_before:.1f} to {th_after:.1f} deg "
            f"between {0.93*v_div:.0f} and {1.07*v_div:.0f} m/s) until the airfoil's "
            f"lift and moment curves flatten out further along (stall, or laminar-bubble "
            f"effects in the XFOIL data) and stiffen it again. A real wing would not "
            f"survive that, so this is reported as the divergence speed."
        )
    elif q_div is not None:
        # The branch only folds above v_max (and nothing ran away below it).
        # Checked after the stall-limited case: a fold far beyond the range
        # must not hide a twist runaway inside it (XFOIL 6.996's polar for
        # the NACA 0012 defaults folds past 100 m/s but still runs away at
        # ~60 m/s, which this ordering used to report as "no divergence").
        stopped_reason = "no_divergence_in_range"
        q_div = v_div = theta_div = alpha_div = None
    elif branch["saturates"]:
        stopped_reason = "no_divergence_possible"
    else:
        q_edge = float(branch["q"][-1]) if len(branch["q"]) else 0.0
        if q_edge >= q_max:
            stopped_reason = "no_divergence_in_range"
        else:
            stopped_reason = "polar_range_exceeded"
            v_edge = math.sqrt(2 * q_edge / rho)
            warnings.append(
                f"Above {v_edge:.1f} m/s the equilibrium twist carries the section past "
                f"the angles XFOIL could converge ({polar.alpha_min:.1f} to "
                f"{polar.alpha_max:.1f} deg), so higher speeds could not be assessed."
            )

    history = []
    for v in _speed_grid(v_start, v_step, v_max):
        q = 0.5 * rho * v ** 2
        th = _interp_on_branch(branch, q, "theta_deg")
        if th is None:
            break
        a = alpha_root + th
        k_eff = _interp_on_branch(branch, q, "k_eff")
        history.append({
            "v": v, "q": q,
            "alpha_elastic_deg": th,
            "alpha_total_deg": a,
            "cl": float(polar.cl(a)),
            "k_eff": k_eff,
            "lift_per_span": q * chord * float(polar.cl(a)),
        })
    if v_div is not None and all(abs(h["v"] - v_div) > 1e-6 for h in history):
        # Put the divergence point itself on the curves (the user's speed
        # grid is usually too coarse to land on it, which made the plotted
        # stiffness minimum look much shallower than the reported one).
        a = alpha_div
        k_at = 0.0 if stopped_reason == "divergence_found" else _interp_on_branch(branch, q_div, "k_eff")
        history.append({"v": v_div, "q": q_div, "alpha_elastic_deg": theta_div,
                        "alpha_total_deg": a, "cl": float(polar.cl(a)), "k_eff": k_at,
                        "lift_per_span": q_div * chord * float(polar.cl(a))})
        history.sort(key=lambda h: h["v"])

    # Stall along the loaded path
    stall = polar.stall_alpha_pos if branch["direction"] > 0 else polar.stall_alpha_neg
    if stall is not None and history:
        for h in history:
            past = h["alpha_total_deg"] >= stall if branch["direction"] > 0 else h["alpha_total_deg"] <= stall
            if past:
                warnings.append(
                    f"The twisted section reaches stall (about {stall:.1f} deg) at "
                    f"{h['v']:.1f} m/s. Beyond that the result relies on post-stall "
                    f"XFOIL data, which is much less reliable."
                )
                break

    if stopped_reason in ("divergence_found", "stall_limited_divergence") and linear["v_div"]:
        gap = abs(v_div - linear["v_div"]) / linear["v_div"]
        if gap > 0.15:
            warnings.append(
                f"Nonlinear divergence ({v_div:.1f} m/s) differs from the linear "
                f"estimate ({linear['v_div']:.1f} m/s) by {gap*100:.0f}%: the lift and "
                f"moment curves aren't straight over the twist range involved, so the "
                f"nonlinear value is the one to trust."
            )

    return {
        "v_div": v_div, "q_div": q_div,
        "alpha_elastic_at_div_deg": theta_div, "alpha_total_at_div_deg": alpha_div,
        "stopped_reason": stopped_reason,
        "min_stiffness_ratio": k_min_ratio,
        "v_at_min_stiffness": v_k_min,
        "linear": linear,
        "history": history,
        "warnings": warnings,
    }


def analyze_divergence(work_dir, seed_filename, reynolds, ncrit,
                       alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                       v_start=5.0, v_step=2.0, v_max=150.0):
    """Full divergence analysis: one XFOIL polar, then pure Python."""
    polar = run_polar(work_dir, seed_filename, reynolds, ncrit, anchor_alpha=alpha_root)
    result = divergence_from_polar(polar, alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                                   v_start, v_step, v_max)
    result["polar"] = polar.to_dict()
    return result


def find_divergence_speed_from_velocity(work_dir, seed_filename, reynolds, ncrit,
                                        alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                                        v_start=5.0, v_step=2.0, v_max=150.0):
    """Backwards-compatible wrapper (old return shape + everything new)."""
    r = analyze_divergence(work_dir, seed_filename, reynolds, ncrit, alpha_root, k_alpha,
                           x_ea_over_c, chord, span, rho, v_start, v_step, v_max)
    r["history_tuples"] = [(h["q"], h["alpha_elastic_deg"], h["cl"]) for h in r["history"]]
    return r
