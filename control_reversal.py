"""
control_reversal.py
=====================

Module 2 of the aeroelasticity feature: trailing-edge flap / aileron
control reversal on the same torsion-only typical section as Module 1.

Physics
-------
A flap deflection delta adds lift (Cl_delta) and a nose-down pitching
moment (Cm_delta). About the elastic axis that moment twists the section
nose-down, which removes lift. At equilibrium (linearised in delta about
the delta = 0 equilibrium at each airspeed):

    dtheta/ddelta   = q*S*c * Cm_EA,delta / K_eff
    Cm_EA,delta     = Cm_c4,delta + Cl_delta * (x_EA/c - 0.25)
    K_eff           = k_alpha - q*S*c * dCm_EA/dalpha      (per rad)
    dCl/ddelta|ae   = Cl_delta + Cl_alpha * dtheta/ddelta

Control effectiveness  eta = (dCl/ddelta)|aeroelastic / Cl_delta  starts at
1 and falls with airspeed; the reversal speed is where eta = 0. The whole
thing is evaluated analytically along the exact equilibrium branch traced
by static_divergence.trace_equilibrium_branch, so there is no root
finding and no finite-difference re-solving per airspeed.

Linear cross-check (Hodges & Pierce / Bisplinghoff):
    q_R = -k_alpha * Cl_delta / (S * c * a0 * Cm_AC,delta)
with Cm_AC,delta the flap moment derivative about the aerodynamic centre;
notably independent of the elastic-axis position.

Flap derivatives
----------------
"xfoil" (default): measured with XFOIL's own GDES FLAP at +/-2 deg around
the undeflected polar (hinge at mid-thickness, x_h = 1 - E_f), as a
function of alpha, so viscous flap-effectiveness loss is captured.
"thin_airfoil": Glauert thin-airfoil results scaled by a0_real / 2*pi:

    theta_f = arccos(2*E_f - 1)
    dCl/ddelta   = 2*(pi - theta_f + sin(theta_f))
    dCm_c4/ddelta = 0.5*sin(theta_f)*(cos(theta_f) - 1)

Both are always reported so they can be compared; if the XFOIL flap
polars fail to converge the thin-airfoil values are used with a warning.
"""

import math

import numpy as np
from scipy.interpolate import PchipInterpolator

import static_divergence as sd

FLAP_TEST_DEFLECTION_DEG = 2.0


def flap_derivatives(flap_chord_fraction, a0_real_per_rad):
    """Thin-airfoil (dCl/ddelta, dCm_c4/ddelta) per radian, scaled by the
    real lift-curve slope."""
    Ef = flap_chord_fraction
    theta_f = math.acos(2 * Ef - 1)
    dcl_ideal = 2 * (math.pi - theta_f + math.sin(theta_f))
    dcm_ideal = 0.5 * math.sin(theta_f) * (math.cos(theta_f) - 1)
    scale = a0_real_per_rad / (2 * math.pi)
    return dcl_ideal * scale, dcm_ideal * scale


class FlapDerivatives:
    """Cl_delta(alpha), Cm_c4_delta(alpha) per radian of flap deflection."""

    def __init__(self, alpha, cl_d, cm_d, source):
        self.source = source
        self.alpha = np.asarray(alpha, float)
        self.alpha_min = float(self.alpha[0]) if len(self.alpha) else -1e9
        self.alpha_max = float(self.alpha[-1]) if len(self.alpha) else 1e9
        if len(self.alpha) >= 2:
            self._cl = PchipInterpolator(self.alpha, cl_d, extrapolate=False)
            self._cm = PchipInterpolator(self.alpha, cm_d, extrapolate=False)
            self._const = None
        else:
            self._const = (float(cl_d[0]), float(cm_d[0]))

    @classmethod
    def constant(cls, cl_d, cm_d, source):
        obj = cls([0.0], [cl_d], [cm_d], source)
        obj.alpha_min, obj.alpha_max = -1e9, 1e9
        return obj

    def contains(self, a):
        return self.alpha_min <= a <= self.alpha_max

    def at(self, a):
        if self._const is not None:
            n = np.shape(a)
            return np.full(n, self._const[0]), np.full(n, self._const[1])
        return self._cl(a), self._cm(a)


def measure_flap_derivatives(work_dir, seed_filename, reynolds, ncrit, flap_chord_fraction,
                             anchor_alpha, delta_deg=FLAP_TEST_DEFLECTION_DEG):
    """Central-difference flap derivatives from two XFOIL flap polars."""
    plus = sd.run_polar(work_dir, seed_filename, reynolds, ncrit, anchor_alpha=anchor_alpha,
                        flap=(flap_chord_fraction, delta_deg), tag="flap_plus")
    minus = sd.run_polar(work_dir, seed_filename, reynolds, ncrit, anchor_alpha=anchor_alpha,
                         flap=(flap_chord_fraction, -delta_deg), tag="flap_minus")
    common = sorted(set(np.round(plus.alpha, 4)) & set(np.round(minus.alpha, 4)))
    # contiguous block only
    if len(common) < 3:
        raise sd.XfoilPolarError("Flap polars share too few converged angles")
    d_rad = math.radians(2 * delta_deg)
    a = np.array(common)
    cl_d = (np.asarray(plus.cl(a)) - np.asarray(minus.cl(a))) / d_rad
    cm_d = (np.asarray(plus.cm(a)) - np.asarray(minus.cm(a))) / d_rad
    ok = np.isfinite(cl_d) & np.isfinite(cm_d)
    a, cl_d, cm_d = a[ok], cl_d[ok], cm_d[ok]
    if len(a) < 3:
        raise sd.XfoilPolarError("Flap polars share too few converged angles")
    return FlapDerivatives(a, cl_d, cm_d, "xfoil")


def reversal_from_polar(polar, flap, alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                        flap_chord_fraction, v_start=2.0, v_step=2.0, v_max=150.0):
    """Pure-Python reversal analysis on an existing polar + flap derivatives."""
    S = chord * span
    warnings = []
    q_max = 0.5 * rho * v_max ** 2

    branch = sd.trace_equilibrium_branch(polar, alpha_root, k_alpha, x_ea_over_c, chord, span)
    div = sd.divergence_from_polar(polar, alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                                   v_start, v_step, v_max)

    dcl_alpha = polar._cl.derivative()
    a0_root = polar.aero_params(alpha_root)
    thin_cl_d, thin_cm_d = flap_derivatives(flap_chord_fraction, a0_root["a0_per_rad"])

    # Effectiveness along the dense branch
    th, al, q, k_eff = branch["theta_deg"], branch["alpha_deg"], branch["q"], branch["k_eff"]
    in_flap = (al >= flap.alpha_min) & (al <= flap.alpha_max)
    n_ok = int(np.argmin(in_flap)) if not in_flap.all() else len(al)
    th, al, q, k_eff = th[:n_ok], al[:n_ok], q[:n_ok], k_eff[:n_ok]

    cl_d, cm_d = flap.at(al)
    cl_a = dcl_alpha(al) * 180.0 / math.pi
    cm_ea_d = cm_d + cl_d * (x_ea_over_c - 0.25)
    with np.errstate(divide="ignore", invalid="ignore"):
        dtheta_ddelta = q * S * chord * cm_ea_d / k_eff
        dcl_total = cl_d + cl_a * dtheta_ddelta
        eta = dcl_total / cl_d

    # Stop before divergence (reported separately)
    v_div = div["v_div"] if div["stopped_reason"] in ("divergence_found", "stall_limited_divergence") else None
    q_div = div["q_div"] if v_div is not None else None
    usable = np.isfinite(eta) & (k_eff > 0) & (q <= q_max)
    if q_div is not None:
        usable &= q <= q_div
    last = int(np.argmin(usable)) if not usable.all() else len(eta)

    q_rev = v_rev = alpha_rev = None
    signs = np.sign(eta[:last])
    cross = np.where((signs[:-1] > 0) & (signs[1:] <= 0))[0]
    if len(cross):
        i = int(cross[0])
        f = eta[i] / (eta[i] - eta[i + 1])
        q_rev = float(q[i] + f * (q[i + 1] - q[i]))
        alpha_rev = float(al[i] + f * (al[i + 1] - al[i]))
        v_rev = math.sqrt(2 * q_rev / rho)
        stopped_reason = "reversal_found"
    elif v_div is not None:
        stopped_reason = "divergence_before_reversal"
    elif n_ok < len(branch["alpha_deg"]) and (len(q) == 0 or q[-1] < q_max):
        stopped_reason = "flap_data_range_exceeded"
        v_edge = math.sqrt(2 * q[-1] / rho) if len(q) else 0.0
        warnings.append(
            f"Above {v_edge:.1f} m/s the twisted section leaves the angle range where the "
            f"XFOIL flap polars converged ({flap.alpha_min:.1f} to {flap.alpha_max:.1f} deg)."
        )
    elif len(q) and q[-1] < q_max and div["stopped_reason"] == "polar_range_exceeded":
        stopped_reason = "polar_range_exceeded"
        warnings += [w for w in div["warnings"] if "could not be assessed" in w]
    else:
        stopped_reason = "no_reversal_within_range"

    # Linear theory at the root condition
    cl_d0, cm_d0 = (float(x) for x in flap.at(alpha_root)) if flap.contains(alpha_root) else (thin_cl_d, thin_cm_d)
    x_ac = a0_root["x_ac_over_c"]
    cm_ac_d = cm_d0 + cl_d0 * (x_ac - 0.25)
    lin_q = lin_v = None
    if cm_ac_d < 0 and a0_root["a0_per_rad"] > 0:
        lin_q = -k_alpha * cl_d0 / (S * chord * a0_root["a0_per_rad"] * cm_ac_d)
        lin_v = math.sqrt(2 * lin_q / rho)
    else:
        warnings.append("The flap produces no nose-down moment about the aerodynamic centre "
                        "here, so classical control reversal cannot occur.")

    if v_rev is not None and lin_v:
        gap = abs(v_rev - lin_v) / lin_v
        if gap > 0.15:
            warnings.append(
                f"Nonlinear reversal speed ({v_rev:.1f} m/s) differs from the linear estimate "
                f"({lin_v:.1f} m/s) by {gap*100:.0f}%, because the lift, moment and flap "
                f"curves change over the twist range involved."
            )
    if stopped_reason == "divergence_before_reversal":
        warnings.append(
            f"The section diverges at {v_div:.1f} m/s before the control reverses, so the "
            f"divergence speed is the limiting one."
        )

    # History on the user's speed grid
    history = []
    for v in sd._speed_grid(v_start, v_step, v_max):
        qv = 0.5 * rho * v ** 2
        if last == 0 or qv > q[last - 1]:
            break
        if qv < q[0]:
            idx_eta, idx_th = float(eta[0]), float(th[0] * qv / q[0])
        else:
            idx_eta = float(np.interp(qv, q[:last], eta[:last]))
            idx_th = float(np.interp(qv, q[:last], th[:last]))
        history.append({
            "v": v, "q": qv,
            "alpha_elastic_deg": idx_th,
            "effectiveness": idx_eta,
            "dcl_ddelta_aeroelastic": idx_eta * float(np.interp(qv, q[:last], cl_d[:last])),
        })
    if v_rev is not None:
        history.append({"v": v_rev, "q": q_rev, "alpha_elastic_deg": alpha_rev - alpha_root,
                        "effectiveness": 0.0, "dcl_ddelta_aeroelastic": 0.0})
        history.sort(key=lambda h: h["v"])

    return {
        "v_reversal": v_rev, "q_reversal": q_rev,
        "stopped_reason": stopped_reason,
        "v_div": v_div,
        "a0_per_rad": a0_root["a0_per_rad"],
        "x_ac_over_c": x_ac,
        "flap_derivatives": {
            "source": flap.source,
            "cl_delta_per_rad": cl_d0,
            "cm_c4_delta_per_rad": cm_d0,
            "thin_airfoil_cl_delta_per_rad": thin_cl_d,
            "thin_airfoil_cm_c4_delta_per_rad": thin_cm_d,
        },
        "linear": {"q_reversal": lin_q, "v_reversal": lin_v, "cm_ac_delta_per_rad": cm_ac_d},
        "history": history,
        "warnings": warnings,
    }


def analyze_reversal(work_dir, seed_filename, reynolds, ncrit,
                     alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                     flap_chord_fraction, v_start=2.0, v_step=2.0, v_max=150.0,
                     flap_source="xfoil"):
    """Full reversal analysis: base polar (+ two flap polars), then pure Python."""
    polar = sd.run_polar(work_dir, seed_filename, reynolds, ncrit, anchor_alpha=alpha_root)
    a0 = polar.aero_params(alpha_root)["a0_per_rad"]
    fallback_note = None
    if flap_source == "xfoil":
        try:
            flap = measure_flap_derivatives(work_dir, seed_filename, reynolds, ncrit,
                                            flap_chord_fraction, alpha_root)
            if not flap.contains(alpha_root):
                raise sd.XfoilPolarError("flap polars don't cover the root angle")
        except (sd.XfoilPolarError, RuntimeError) as e:
            fallback_note = (f"XFOIL flap polars didn't converge well enough ({e}); "
                             f"used thin-airfoil flap derivatives instead.")
            flap = FlapDerivatives.constant(*flap_derivatives(flap_chord_fraction, a0), "thin_airfoil")
    else:
        flap = FlapDerivatives.constant(*flap_derivatives(flap_chord_fraction, a0), "thin_airfoil")

    result = reversal_from_polar(polar, flap, alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                                 flap_chord_fraction, v_start, v_step, v_max)
    if fallback_note:
        result["warnings"].insert(0, fallback_note)
    result["polar"] = polar.to_dict()
    return result
