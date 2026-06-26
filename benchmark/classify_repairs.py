#!/usr/bin/env python3
"""
classify_repairs.py
====================

Runs AFTER airfoil_parser_benchmark.py. Takes the list of "rescued" airfoils
(files raw XFOIL failed on but AeroLab's parser fixed) from benchmark_results.csv
and classifies WHICH repair(s) the parser actually applied to each one.

This does NOT re-run XFOIL — classification is pure coordinate-geometry
analysis, so it's fast (seconds, not minutes) even for hundreds of files.

USAGE
    python classify_repairs.py --csv benchmark_results.csv --data-dir <folder of .dat files>

OUTPUT
    repair_classification.csv   one row per rescued airfoil, with repair flags
    repair_summary.txt          counts per repair type (the README/paper table)
"""

import os
import csv
import argparse


# ---------------------------------------------------------------------------
# Raw line tokenizing (mirrors main.py's parse_dat_file, read-only — does not
# import main.py, so this script has zero risk of affecting production code)
# ---------------------------------------------------------------------------
def read_raw_lines(path):
    with open(path, "r", errors="ignore") as f:
        return [l.rstrip("\n").rstrip("\r") for l in f.readlines()]


def tokenize_coords(lines):
    """
    Returns (header, all_numeric_coords, raw_data_lines, filtered_coords).

    all_numeric_coords : every (x,y) pair that parsed as floats, BEFORE the
                          -0.5<=x<=1.5 / -1.0<=y<=1.0 range filter — this is
                          what parse_dat_file() sees before filtering, used
                          to detect whether any out-of-range repair applied.
    filtered_coords     : the same list AFTER the range filter — this is
                          what actually reaches detect_and_merge_sections(),
                          used for the geometry-based checks (Lednicer,
                          winding, LE duplicate, closed TE).
    """
    header = lines[0] if lines else ""
    all_numeric = []
    filtered = []
    raw_data_lines = []
    for line in lines[1:]:
        s = line.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        all_numeric.append((x, y))
        raw_data_lines.append(s)
        if -0.5 <= x <= 1.5 and -1.0 <= y <= 1.0:
            filtered.append((x, y))
    return header, all_numeric, raw_data_lines, filtered


# ---------------------------------------------------------------------------
# Repair detectors — each maps to ONE distinct mechanism actually implemented
# in main.py's parse_dat_file / detect_and_merge_sections. Categories that
# are not separate mechanisms (e.g. "mixed whitespace", "comment lines") are
# intentionally NOT listed here as distinct repair types: both are handled
# incidentally by the same line.strip().split() tokenizing step used for
# every file, not by a dedicated repair branch. Listing them separately
# would overstate the parser's distinct capabilities for the paper.
# ---------------------------------------------------------------------------
def has_lednicer_format(coords):
    """Two-section format: x descends to near-zero, climbs to ~1, then
    descends to near-zero again (a second LE) before the file ends.
    Mechanism: detect_and_merge_sections() section_break detection + merge."""
    xs = [c[0] for c in coords]
    for i in range(1, len(xs)):
        if xs[i] < 0.01 and xs[i - 1] > 0.5:
            return True
    return False


def has_reversed_winding(coords):
    """For a TE-to-TE (Selig-style) file, the point before the LE has
    negative y, indicating lower-surface-first winding, which AeroLab
    reverses to the conventional upper-first order.
    Mechanism: detect_and_merge_sections() TE-to-TE branch, point_before_le_y check."""
    xs = [c[0] for c in coords]
    if not (xs and xs[0] > 0.99 and xs[-1] > 0.99):
        return False  # not TE-to-TE shaped; this mechanism doesn't apply
    le_idx = xs.index(min(xs))
    if le_idx <= 0:
        return False
    return coords[le_idx - 1][1] < 0


def has_duplicate_le_point_lednicer(coords):
    """Lednicer-format files whose lower section repeats the (0,0) leading
    edge point. Only meaningful for Lednicer files; checked independently
    of has_lednicer_format() since both can be true together.
    Mechanism: detect_and_merge_sections() Lednicer branch, lower[1:] strip."""
    xs = [c[0] for c in coords]
    section_break = None
    for i in range(1, len(xs)):
        if xs[i] < 0.01 and xs[i - 1] > 0.5:
            section_break = i
            break
    if section_break is None:
        return False
    lower = coords[section_break:]
    return bool(lower) and abs(lower[0][0]) < 1e-3 and abs(lower[0][1]) < 1e-3


def has_closed_te_at_risk(coords, tol=1e-3):
    """First and last coordinate are (near-)identical at the trailing edge
    — a legitimate closed loop that a naive de-duplication step would
    incorrectly strip (the NACA 6-series bug fixed in this project).
    Mechanism: detect_and_merge_sections() — point intentionally PRESERVED."""
    if len(coords) < 2:
        return False
    return (abs(coords[0][0] - coords[-1][0]) < tol and
            abs(coords[0][1] - coords[-1][1]) < tol)


def has_out_of_range_points(raw_token_pairs):
    """Stray points outside plausible airfoil coordinate bounds — typically
    junk/garbage lines, mis-tokenized headers, or corrupted rows, silently
    dropped by parse_dat_file's range filter.
    Mechanism: parse_dat_file(), -0.5<=x<=1.5 and -1.0<=y<=1.0 filter."""
    return any(not (-0.5 <= x <= 1.5 and -1.0 <= y <= 1.0) for x, y in raw_token_pairs)


def has_non_coordinate_lines(lines):
    """Blank lines, header text, or lines with fewer than 2 numeric tokens
    that parse_dat_file silently skips while scanning for coordinate pairs.
    Mechanism: parse_dat_file(), blank/`len(parts)<2`/ValueError skip.
    NOTE: this is general line-skipping robustness applied uniformly to
    every file (it is what lets comment lines, count-line headers, and
    mixed tab/space rows all pass through harmlessly) rather than a
    dedicated repair branch — reported separately from the five mechanisms
    above as a distinct, lower-level category."""
    if len(lines) < 2:
        return False
    skipped = 0
    for line in lines[1:]:
        s = line.strip()
        if not s:
            skipped += 1
            continue
        parts = s.split()
        if len(parts) < 2:
            skipped += 1
            continue
        try:
            float(parts[0]); float(parts[1])
        except ValueError:
            skipped += 1
    return skipped > 0


def classify(dat_path):
    """Returns a dict of repair_type -> bool for a single raw .dat file."""
    lines = read_raw_lines(dat_path)
    header, all_numeric, raw_data_lines, filtered = tokenize_coords(lines)

    return {
        "lednicer_to_selig":     has_lednicer_format(filtered) if filtered else False,
        "winding_order_fixed":   has_reversed_winding(filtered) if filtered else False,
        "lednicer_le_dedup":     has_duplicate_le_point_lednicer(filtered) if filtered else False,
        "closed_te_preserved":   has_closed_te_at_risk(filtered) if filtered else False,
        "out_of_range_filtered": has_out_of_range_points(all_numeric) if all_numeric else False,
        "non_coord_lines_skipped": has_non_coordinate_lines(lines),
    }


REPAIR_LABELS = {
    "lednicer_to_selig":       "Lednicer two-section format merged to single Selig loop",
    "winding_order_fixed":     "Reversed Selig winding order corrected",
    "lednicer_le_dedup":       "Duplicate Lednicer leading-edge point removed",
    "closed_te_preserved":     "Closed trailing edge correctly preserved (not stripped)",
    "out_of_range_filtered":   "Out-of-range / garbage coordinate rows filtered",
    "non_coord_lines_skipped": "Non-coordinate lines skipped (blank/header/comment/count-line)",
}


def main():
    ap = argparse.ArgumentParser(description="Classify repairs applied to rescued airfoils")
    ap.add_argument("--csv", required=True, help="benchmark_results.csv from airfoil_parser_benchmark.py")
    ap.add_argument("--data-dir", required=True, help="Folder containing the original .dat files")
    ap.add_argument("--out-prefix", default="repair")
    args = ap.parse_args()

    with open(args.csv, newline="") as f:
        rows = list(csv.DictReader(f))

    rescued = [r for r in rows
               if r.get("raw_converged") == "False" and r.get("parsed_converged") == "True"]

    print(f"[classify] {len(rescued)} rescued airfoils found in {args.csv}")

    out_rows = []
    type_counts = {k: 0 for k in REPAIR_LABELS}
    no_detected_cause = 0

    for r in rescued:
        name = r["airfoil"]
        dat_path = os.path.join(args.data_dir, name + ".dat")
        if not os.path.exists(dat_path):
            print(f"  WARNING: {dat_path} not found, skipping")
            continue

        flags = classify(dat_path)
        any_flag = any(flags.values())
        if not any_flag:
            no_detected_cause += 1

        for k, v in flags.items():
            if v:
                type_counts[k] += 1

        out_row = {"airfoil": name}
        out_row.update(flags)
        out_rows.append(out_row)

    if out_rows:
        with open(f"{args.out_prefix}_classification.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["airfoil"] + list(REPAIR_LABELS.keys()))
            w.writeheader()
            w.writerows(out_rows)

    lines_out = [
        "================================================================",
        "AeroLab Parser — Repair Type Classification",
        "================================================================",
        f"Rescued airfoils analysed: {len(out_rows)}",
        "",
        "Repair Type                                              Count   %",
        "----------------------------------------------------------------------",
    ]
    for k, label in REPAIR_LABELS.items():
        n = type_counts[k]
        pct = round(100.0 * n / len(out_rows), 1) if out_rows else 0.0
        lines_out.append(f"{label:<55s} {n:5d}  {pct:5.1f}%")
    lines_out.append("----------------------------------------------------------------------")
    lines_out.append(f"{'No specific cause auto-detected':<55s} {no_detected_cause:5d}")
    lines_out.append("")
    lines_out.append("Note: a single airfoil can have multiple repair types simultaneously")
    lines_out.append("(percentages do not need to sum to 100%).")
    report = "\n".join(lines_out)

    with open(f"{args.out_prefix}_summary.txt", "w") as f:
        f.write(report + "\n")

    print("\n" + report)


if __name__ == "__main__":
    main()
