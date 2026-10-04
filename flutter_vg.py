"""
flutter_vg.py
==============

Module 3 (V-g / p-k method) of the aeroelasticity feature: 2-DOF
pitch+plunge flutter using the exact unsteady (Theodorsen) airload.

Source for the governing equations: Berci, "On Aerodynamic Models for
Flutter Analysis: A Systematic Overview and Comparative Assessment",
Applied Mechanics 2021, 2(3), 516-541 -- chosen specifically because it
gives the full unsteady airload in an explicitly implementable form
(its Eq. 25) AND provides several independently published validation
cases with complete parameters and results tables, not just a formula
to trust blindly.

SIGN CONVENTIONS (matching the source exactly -- easy to get backwards,
so stated explicitly): h positive UPWARDS, theta (pitch) positive
CLOCKWISE (i.e. nose-down, NOT the more common nose-up convention),
lift positive upwards, moment positive clockwise, x measured from the
aerofoil's MID-CHORD (not leading edge), positive aft. b = semichord =
c/2. x_EA here is the elastic axis location relative to mid-chord in
the same units as b (not a chord fraction like in Modules 1-2).

Structural equations of motion (source Eq. 1):
  m*[h'' - (xCG-xEA)*theta''] + kh*h = dL
  mu*theta'' - m*(xCG-xEA)*[h'' - (xCG-xEA)*theta''] + ktheta*theta = dM

Unsteady aerodynamic loads (source Eq. 25, the "US" exact model):
  V = U*theta - h' + (b/2 - xEA)*theta'
  dL = 2*pi*rho*U*b*C(k)*V + pi*rho*b^2*(U*theta' - h'' - xEA*theta'')
  dM = 2*pi*rho*U*b*(b/2+xEA)*C(k)*V
       - pi*rho*b^2*[(b/2-xEA)*U*theta' + xEA*h'' + (b^2/8+xEA^2)*theta'']

Theodorsen's function C(k) = H1(2)(k) / [H1(2)(k) + i*H0(2)(k)], with
H_n^(2) the Hankel function of the second kind (source Eq. 23).
"""

import numpy as np
from scipy.special import hankel2

import static_divergence as sd

PLOT_POINTS = 120  # resolution of the returned V-g / V-f curves


def theodorsen_C(k):
    """Theodorsen's lift-deficiency function C(k). k -> 0 gives C -> 1
    (quasi-steady limit); k -> infinity gives C -> 0.5. Both are known
    limiting properties, checked directly below before trusting the
    full sweep."""
    if k == 0:
        return 1.0 + 0.0j
    H1 = hankel2(1, k)
    H0 = hankel2(0, k)
    return H1 / (H1 + 1j * H0)


def build_matrices(m, mu, xCG, xEA, kh, ktheta, b, rho, U, k, a0_scale=1.0):
    """
    Same as before, with an added a0_scale factor (default 1.0, exactly
    reproducing the original, validated equations) that scales the
    circulatory (2*pi-based) terms by a0_real/(2*pi). This is how real,
    XFOIL-measured lift-curve slope gets substituted for thin-airfoil
    theory's assumed 2*pi value -- the same "scale by the real,
    measured a0" approach validated in Module 2's flap effectiveness.
    """
    Ck = theodorsen_C(k)
    d = xCG - xEA

    Ms = np.array([
        [m, -m * d],
        [-m * d, mu + m * d ** 2],
    ], dtype=complex)
    Ks = np.array([
        [kh, 0],
        [0, ktheta],
    ], dtype=complex)

    Ma = np.array([
        [-np.pi * rho * b ** 2, -np.pi * rho * b ** 2 * xEA],
        [-np.pi * rho * b ** 2 * xEA, -np.pi * rho * b ** 2 * (b ** 2 / 8 + xEA ** 2)],
    ], dtype=complex)

    # circulatory terms (those carrying the 2*pi*rho*U*b*C(k) factor,
    # i.e. the thin-airfoil lift-curve-slope-dependent part) scaled by
    # a0_scale; non-circulatory apparent-inertia terms (Ma above, and
    # the pi*rho*b^2*U terms below) are NOT lift-curve-slope-dependent
    # and are left untouched
    Ca = np.array([
        [-2 * np.pi * rho * U * b * Ck * a0_scale,
         2 * np.pi * rho * U * b * Ck * (b / 2 - xEA) * a0_scale + np.pi * rho * b ** 2 * U],
        [-2 * np.pi * rho * U * b * (b / 2 + xEA) * Ck * a0_scale,
         2 * np.pi * rho * U * b * (b / 2 + xEA) * Ck * (b / 2 - xEA) * a0_scale
         - np.pi * rho * b ** 2 * (b / 2 - xEA) * U],
    ], dtype=complex)

    Ka = np.array([
        [0, 2 * np.pi * rho * U ** 2 * b * Ck * a0_scale],
        [0, 2 * np.pi * rho * U ** 2 * b * (b / 2 + xEA) * Ck * a0_scale],
    ], dtype=complex)

    M = Ms - Ma
    C = -Ca
    K = Ks - Ka
    return M, C, K


def _track_single_mode(m, mu, xCG, xEA, kh, ktheta, b, rho, U, omega_target, max_iters=60, tol=1e-6, a0_scale=1.0):
    """
    Iterates the p-k self-consistency condition (k = b*omega/U) for
    ONE mode, tracked by proximity to omega_target at each step
    (continuity), rather than by re-picking whichever mode is
    currently least damped. Safe as long as omega_target starts close
    to the intended mode's actual frequency and stays in its basin --
    which solve_at_speed below ensures by anchoring two independent
    calls to this function at the two uncoupled structural
    frequencies, rather than a single ambiguous starting guess.

    Returns dict: {"omega": float, "damping": float, "k": float,
    "converged": bool}.
    """
    k = b * omega_target / U if U > 0 else 0.0
    crit = None
    for _ in range(max_iters):
        M, C, K = build_matrices(m, mu, xCG, xEA, kh, ktheta, b, rho, U, k, a0_scale=a0_scale)
        n = 2
        Z = np.zeros((n, n), dtype=complex)
        I = np.eye(n, dtype=complex)
        Minv = np.linalg.inv(M)
        A = np.block([[Z, I], [-Minv @ K, -Minv @ C]])
        eigvals = np.linalg.eigvals(A)
        physical = eigvals[eigvals.imag > 1e-8]
        if len(physical) == 0:
            return {"omega": None, "damping": None, "k": None, "converged": False}
        crit = physical[np.argmin(np.abs(physical.imag - omega_target))]
        new_omega = crit.imag
        new_k = b * new_omega / U if U > 0 else 0.0
        if abs(new_k - k) < tol:
            return {"omega": new_omega, "damping": crit.real, "k": new_k, "converged": True}
        k = new_k
        omega_target = new_omega
    return {"omega": omega_target, "damping": crit.real if crit is not None else None,
            "k": k, "converged": False}


def solve_modes_at_speed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, max_iters=60, tol=1e-6, a0_scale=1.0):
    """
    p-k solve of BOTH structural modes at airspeed U, each anchored at its
    own uncoupled natural frequency (see solve_at_speed for why this
    anchoring matters). Returns (plunge_mode_result, pitch_mode_result),
    each {"omega", "damping", "k", "converged"}.
    """
    omega_h = np.sqrt(kh / m)
    mu_theta = mu + m * (xCG - xEA) ** 2
    omega_theta = np.sqrt(ktheta / mu_theta)
    result_h = _track_single_mode(m, mu, xCG, xEA, kh, ktheta, b, rho, U, omega_h,
                                  max_iters=max_iters, tol=tol, a0_scale=a0_scale)
    result_theta = _track_single_mode(m, mu, xCG, xEA, kh, ktheta, b, rho, U, omega_theta,
                                      max_iters=max_iters, tol=tol, a0_scale=a0_scale)
    return result_h, result_theta


def solve_at_speed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, k_guess=0.3, max_iters=60, tol=1e-6, a0_scale=1.0):
    """
    p-k method at a single airspeed U. Tracks BOTH structural modes to
    self-consistency independently (each anchored near its own
    uncoupled natural frequency), then returns whichever converged mode
    is more critical (least damped) -- the correct quantity for flutter
    analysis.

    This two-stage fix replaced two earlier, each-flawed approaches:
    (1) always re-picking whichever mode had the least damping at each
    trial k -- the selection could flip between physical modes
    mid-iteration (confirmed at U=1.5 for Case A); (2) tracking a single
    mode by frequency continuity from one ambiguous starting guess --
    this silently locked onto the WRONG, non-fluttering mode for a whole
    sweep. Anchoring two separate starting points (one per structural
    mode) fixes both.

    k_guess is accepted but unused (kept for call compatibility).
    Returns dict: {"omega", "damping", "k", "converged"} for the more
    critical (least damped) mode.
    """
    del k_guess
    result_h, result_theta = solve_modes_at_speed(m, mu, xCG, xEA, kh, ktheta, b, rho, U,
                                                  max_iters=max_iters, tol=tol, a0_scale=a0_scale)
    candidates = [r for r in (result_h, result_theta) if r["converged"]]
    if not candidates:
        return {"omega": None, "damping": None, "k": None, "converged": False}
    return max(candidates, key=lambda r: r["damping"])


def _mode_entry(r):
    if not r["converged"]:
        return None
    return {"damping": float(r["damping"]), "omega": float(r["omega"]),
            "freq_hz": float(r["omega"]) / (2 * np.pi), "k": float(r["k"])}


def find_flutter_speed(m, mu, xCG, xEA, kh, ktheta, b, rho,
                       U_start=0.1, U_step=0.05, U_max=50.0, k_guess=0.3, a0_scale=1.0):
    """
    Sweeps airspeed upward, tracking the least-damped mode's damping
    (real part of s) until it crosses zero -- the flutter speed -- then
    refines the crossing by bisection.

    Returns dict:
      U_flutter, omega_flutter, k_flutter   (None if not found)
      stopped_reason: "flutter_found" | "unstable_at_start" | "no_flutter_in_range"
      history: [(U, damping, omega, k), ...]      (critical mode, legacy shape)
      modes:   [{"U", "plunge": {...}|None, "pitch": {...}|None}, ...]
      skipped_speeds: speeds where neither mode's p-k iteration converged
      critical_mode: "plunge" | "pitch" | None
    """
    history, modes, skipped = [], [], []
    prev_damping = None
    U = U_start
    first_checked = False

    def done(reason, U_f=None, omega=None, k=None, critical=None):
        return {"U_flutter": U_f, "omega_flutter": omega, "k_flutter": k,
                "stopped_reason": reason, "history": history, "modes": modes,
                "skipped_speeds": skipped, "critical_mode": critical}

    while U <= U_max + 1e-12:
        rh, rt = solve_modes_at_speed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, a0_scale=a0_scale)
        modes.append({"U": float(U), "plunge": _mode_entry(rh), "pitch": _mode_entry(rt)})
        candidates = [r for r in (rh, rt) if r["converged"]]
        if not candidates:
            skipped.append(float(U))
            U += U_step
            continue
        result = max(candidates, key=lambda r: r["damping"])
        damping = result["damping"]
        history.append((U, damping, result["omega"], result["k"]))

        if not first_checked:
            first_checked = True
            if damping >= 0:
                return done("unstable_at_start")

        if prev_damping is not None and prev_damping < 0 <= damping:
            U_lo, U_hi = U - U_step, U
            d_lo = prev_damping
            for _ in range(20):
                U_mid = 0.5 * (U_lo + U_hi)
                mid_result = solve_at_speed(m, mu, xCG, xEA, kh, ktheta, b, rho, U_mid, a0_scale=a0_scale)
                if not mid_result["converged"]:
                    break
                d_mid = mid_result["damping"]
                if d_lo < 0 <= d_mid:
                    U_hi = U_mid
                else:
                    U_lo, d_lo = U_mid, d_mid
            U_flutter = 0.5 * (U_lo + U_hi)
            fh, ft = solve_modes_at_speed(m, mu, xCG, xEA, kh, ktheta, b, rho, U_flutter, a0_scale=a0_scale)
            conv = [(name, r) for name, r in (("plunge", fh), ("pitch", ft)) if r["converged"]]
            if conv:
                critical, final = max(conv, key=lambda nr: nr[1]["damping"])
            else:
                critical, final = None, {"omega": None, "k": None}
            return done("flutter_found", U_flutter, final["omega"], final["k"], critical)

        prev_damping = damping
        U += U_step

    return done("no_flutter_in_range")


def get_real_aero_params(work_dir, seed_filename, reynolds, ncrit, alpha_ref, delta=0.5):
    """
    Real, XFOIL-measured lift-curve slope a0 (per radian) and
    aerodynamic-centre location near alpha_ref, from one converged
    viscous polar over alpha_ref +/- 5 deg (least-squares slope over
    +/- 1 deg of the raw converged points).

    Previously this made two single-angle XFOIL calls and parsed the
    first "CL =" line of the console output, which is the first viscous
    iteration rather than the converged solution.

    x_AC is reported, not used in the matrices: the Theodorsen matrices
    above assume the aerodynamic centre at quarter chord; if x_AC is more
    than a couple of percent chord away, treat the result as approximate.
    delta is kept for call compatibility and ignored.

    Returns {"a0_per_rad", "a0_scale", "x_ac_over_c",
             "x_ac_deviation_from_quarter_chord"}.
    """
    del delta
    polar = sd.run_polar(work_dir, seed_filename, reynolds, ncrit,
                         alpha_min=alpha_ref - 5.0, alpha_max=alpha_ref + 5.0,
                         alpha_step=0.5, anchor_alpha=alpha_ref, tag="flutter")
    if not polar.contains(alpha_ref):
        raise sd.XfoilPolarError(f"XFOIL did not converge near alpha_ref={alpha_ref} deg")
    p = polar.aero_params(alpha_ref)
    a0 = p["a0_per_rad"]
    return {
        "a0_per_rad": a0,
        "a0_scale": a0 / (2 * np.pi),
        "x_ac_over_c": p["x_ac_over_c"],
        "x_ac_deviation_from_quarter_chord": p["x_ac_over_c"] - 0.25,
    }


def analyze_flutter(work_dir, seed_filename, reynolds, ncrit, alpha_ref,
                    m, mu, xCG, xEA, kh, ktheta, b, rho,
                    use_real_airfoil_data=True, U_start=0.5, U_step=0.5, U_max=100.0):
    """Endpoint-level wrapper: optional real-airfoil a0, then the sweep,
    plus human-readable warnings."""
    warnings = []
    aero_info = None
    a0_scale = 1.0
    if use_real_airfoil_data:
        aero_info = get_real_aero_params(work_dir, seed_filename, reynolds, ncrit, alpha_ref)
        a0_scale = aero_info["a0_scale"]
        dev = aero_info["x_ac_deviation_from_quarter_chord"]
        if abs(dev) > 0.02:
            warnings.append(
                f"This airfoil's aerodynamic centre is at {aero_info['x_ac_over_c']*100:.1f}% "
                f"chord, not 25%. The unsteady (Theodorsen) model assumes 25%, so treat the "
                f"flutter speed as approximate."
            )

    result = find_flutter_speed(m, mu, xCG, xEA, kh, ktheta, b, rho,
                                U_start=U_start, U_step=U_step, U_max=U_max, a0_scale=a0_scale)

    # Plot curves for the V-g / V-f diagrams on their own even grid, running
    # a little past the flutter point so the damping visibly crosses zero.
    # Plotting only -- U_flutter comes from the sweep + bisection above.
    if result["stopped_reason"] == "flutter_found":
        U_end = min(U_max, 1.3 * result["U_flutter"])
    elif result["stopped_reason"] == "unstable_at_start":
        U_end = U_start
    else:
        U_end = U_max
    if U_end > U_start:
        plot_modes = []
        for U in np.linspace(U_start, U_end, PLOT_POINTS):
            rh, rt = solve_modes_at_speed(m, mu, xCG, xEA, kh, ktheta, b, rho, U, a0_scale=a0_scale)
            plot_modes.append({"U": float(U), "plunge": _mode_entry(rh), "pitch": _mode_entry(rt)})
        result["modes"] = plot_modes

    if result["stopped_reason"] == "unstable_at_start":
        warnings.append(
            f"The section is already unstable at the first swept speed ({U_start:g} m/s), so "
            f"the flutter speed is below it. Lower 'Sweep from'."
        )
    if result["skipped_speeds"]:
        s = result["skipped_speeds"]
        warnings.append(
            f"The p-k iteration did not converge at {len(s)} of the swept speeds "
            f"(e.g. {s[0]:g} m/s); they are left out of the plots."
        )

    omega_h = float(np.sqrt(kh / m))
    omega_theta = float(np.sqrt(ktheta / (mu + m * (xCG - xEA) ** 2)))
    if xCG <= xEA:
        warnings.append(
            "The centre of gravity is at or ahead of the elastic axis. Classical "
            "bending-torsion flutter usually needs the CG aft of the elastic axis."
        )

    result.update({
        "aero_info": aero_info,
        "a0_scale": a0_scale,
        "uncoupled": {"omega_h": omega_h, "omega_theta": omega_theta,
                      "freq_ratio": omega_h / omega_theta if omega_theta else None},
        "warnings": warnings,
    })
    return result
