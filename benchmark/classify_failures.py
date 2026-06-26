#!/usr/bin/env python3
"""
classify_failures.py
====================

Analyses the 142 airfoils that failed both raw XFOIL and AeroLab's parser,
and classifies WHY they failed geometrically.

USAGE
    python classify_failures.py --csv benchmark_results.csv \
        --data-dir "C:\\Users\\NATHAN~1\\AppData\\Local\\Temp\\uiuc_airfoils_coord"

OUTPUT
    failure_classification.csv   one row per failed airfoil with category
    failure_summary.txt          counts per failure category
"""

import os
import csv
import math
import argparse


# ---------------------------------------------------------------------------
# Coordinate loading
# ---------------------------------------------------------------------------
def load_coords(path):
    """Load and range-filter coordinates from a .dat file."""
    coords = []
    with open(path, errors='ignore') as f:
        lines = f.readlines()
    for line in lines[1:]:
        s = line.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
            if -0.5 <= x <= 1.5 and -1.0 <= y <= 1.0:
                coords.append((x, y))
        except ValueError:
            continue
    return coords


def load_all_coords_unfiltered(path):
    """Load ALL numeric coordinate pairs before range filter."""
    coords = []
    with open(path, errors='ignore') as f:
        lines = f.readlines()
    for line in lines[1:]:
        s = line.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
            coords.append((x, y))
        except ValueError:
            continue
    return coords


# ---------------------------------------------------------------------------
# Geometric classifiers
# ---------------------------------------------------------------------------
def is_multi_element(coords):
    """Multiple TE-to-LE passes = multi-element configuration."""
    xs = [c[0] for c in coords]
    passes = 0
    state = "start"
    for x in xs:
        if x <= 0.05 and state in ("start", "high"):
            state = "low"
        elif x >= 0.90 and state == "low":
            passes += 1
            state = "high"
    return passes >= 2


def is_lednicer(coords):
    """Two-section Lednicer format."""
    xs = [c[0] for c in coords]
    for i in range(1, len(xs)):
        if xs[i] < 0.01 and xs[i - 1] > 0.5:
            return True
    return False


def has_non_monotone_surface(coords):
    """
    Check if either surface has non-monotone x distribution — a sign of
    self-intersecting or badly ordered coordinates that XFOIL can't panel.
    """
    if len(coords) < 6:
        return False
    xs = [c[0] for c in coords]
    le_idx = min(range(len(xs)), key=lambda i: xs[i])
    upper_x = [coords[i][0] for i in range(le_idx + 1)]
    lower_x = [coords[i][0] for i in range(le_idx, len(coords))]
    upper_mono = all(upper_x[i] >= upper_x[i + 1] - 1e-4
                     for i in range(len(upper_x) - 1))
    lower_mono = all(lower_x[i] <= lower_x[i + 1] + 1e-4
                     for i in range(len(lower_x) - 1))
    return not (upper_mono and lower_mono)


def estimate_max_camber(coords):
    """Rough max camber estimate from midpoint between upper and lower surfaces."""
    if len(coords) < 6:
        return 0.0
    xs = [c[0] for c in coords]
    le_idx = min(range(len(xs)), key=lambda i: xs[i])
    upper = {round(c[0], 3): c[1] for c in coords[:le_idx + 1]}
    lower = {round(c[0], 3): c[1] for c in coords[le_idx:]}
    cambers = []
    for x in upper:
        if x in lower:
            cambers.append(abs((upper[x] + lower[x]) / 2.0))
    return max(cambers) if cambers else 0.0


def estimate_max_thickness(coords):
    """Rough max thickness estimate."""
    if len(coords) < 6:
        return 0.0
    xs = [c[0] for c in coords]
    le_idx = min(range(len(xs)), key=lambda i: xs[i])
    upper = {round(c[0], 3): c[1] for c in coords[:le_idx + 1]}
    lower = {round(c[0], 3): c[1] for c in coords[le_idx:]}
    thicknesses = []
    for x in upper:
        if x in lower:
            thicknesses.append(upper[x] - lower[x])
    return max(thicknesses) if thicknesses else 0.0


def has_extreme_geometry(coords):
    """Flags physically unusual airfoil geometry."""
    camber = estimate_max_camber(coords)
    thickness = estimate_max_thickness(coords)
    return camber > 0.12 or thickness > 0.30, camber, thickness


# ---------------------------------------------------------------------------
# Main categorisation logic
# ---------------------------------------------------------------------------
CATEGORIES = {
    'multi_element':        'Multi-element configuration (XFOIL scope limitation)',
    'too_few_points':       'Insufficient coordinate points after parsing (<10)',
    'non_monotone':         'Non-monotone surface coordinates (possible self-intersection)',
    'lednicer_hard':        'Lednicer format converted but XFOIL still failed to converge',
    'extreme_geometry':     'Extreme camber (>12%) or thickness (>30%) — hard to converge',
    'convergence_failure':  'Clean geometry, XFOIL viscous convergence failure',
}


def classify_failure(dat_path):
    all_coords = load_all_coords_unfiltered(dat_path)
    coords = [c for c in all_coords if -0.5 <= c[0] <= 1.5 and -1.0 <= c[1] <= 1.0]

    if len(coords) < 10:
        return 'too_few_points', 0.0, 0.0

    if is_multi_element(coords):
        return 'multi_element', 0.0, 0.0

    lednicer = is_lednicer(coords)
    non_mono = has_non_monotone_surface(coords)
    extreme, camber, thickness = has_extreme_geometry(coords)

    if non_mono:
        return 'non_monotone', camber, thickness
    if lednicer:
        return 'lednicer_hard', camber, thickness
    if extreme:
        return 'extreme_geometry', camber, thickness
    return 'convergence_failure', camber, thickness


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Classify why both-failed airfoils failed")
    ap.add_argument("--csv", required=True, help="benchmark_results.csv")
    ap.add_argument("--data-dir", required=True, help="Folder of .dat files")
    ap.add_argument("--out-prefix", default="failure")
    args = ap.parse_args()

    with open(args.csv, newline="") as f:
        rows = list(csv.DictReader(f))

    both_failed = [r for r in rows
                   if r['raw_converged'] == 'False'
                   and r['parsed_converged'] == 'False'
                   and r.get('multi_element', '') != 'True']

    print(f"[classify] Analysing {len(both_failed)} both-failed airfoils...")

    counts = {k: 0 for k in CATEGORIES}
    out_rows = []
    missing = 0

    for r in both_failed:
        name = r['airfoil']
        path = os.path.join(args.data_dir, name + '.dat')
        if not os.path.exists(path):
            missing += 1
            continue

        cat, camber, thickness = classify_failure(path)
        counts[cat] += 1
        out_rows.append({
            'airfoil': name,
            'category': cat,
            'est_max_camber': f"{camber:.3f}",
            'est_max_thickness': f"{thickness:.3f}",
        })

    # Write CSV
    if out_rows:
        with open(f"{args.out_prefix}_classification.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            w.writeheader()
            w.writerows(out_rows)

    # Write summary
    total_classified = sum(counts.values())
    lines = [
        "================================================================",
        "AeroLab — Failure Analysis of Both-Failed Airfoils",
        "================================================================",
        f"Both-failed airfoils: {len(both_failed)}",
        f"Successfully classified: {total_classified}",
        f"File not found (skipped): {missing}",
        "",
        "Category                                                  Count    %",
        "----------------------------------------------------------------------",
    ]
    for cat, label in CATEGORIES.items():
        n = counts[cat]
        pct = round(100.0 * n / total_classified, 1) if total_classified else 0.0
        lines.append(f"{label:<55s} {n:5d}  {pct:5.1f}%")
    lines.append("----------------------------------------------------------------------")

    report = "\n".join(lines)
    with open(f"{args.out_prefix}_summary.txt", "w") as f:
        f.write(report + "\n")
    print("\n" + report)


if __name__ == "__main__":
    main()
