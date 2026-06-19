#!/usr/bin/env python3
"""
xfoil_paneling_test.py
======================

Diagnoses why certain airfoil .dat files (notably NACA 6-series laminar
airfoils) fail to converge in XFOIL, by trying several leading-edge
paneling strategies and reporting which ones successfully produce a Cp file.

USAGE
-----
    python xfoil_paneling_test.py path/to/airfoil.dat [Re] [alpha]

    # examples
    python xfoil_paneling_test.py naca65210.dat
    python xfoil_paneling_test.py naca65210.dat 200000 5
    python xfoil_paneling_test.py naca663218.dat 100000 3

WHAT IT DOES
------------
Runs the SAME airfoil through XFOIL under several different command sequences:

    1. baseline      : LOAD -> PANE          (what your current code does)
    2. alfa_step     : LOAD -> PANE -> ALFA 0 then ALFA target
    3. ppar_160      : LOAD -> PPAR(160 panels) -> PANE -> alfa step
    4. ppar_220_le   : LOAD -> PPAR(220 panels, denser LE) -> PANE -> alfa step

For each strategy it reports:
    - whether XFOIL converged
    - the final CL/CD/CM if available
    - whether the Cp output file was written

The goal is to find the FIRST strategy that reliably works, so you know
exactly what to change in main.py.

REQUIREMENTS
------------
    - XFOIL installed and on your PATH (or set XFOIL_PATH below)
    - On Linux you may need a virtual display. If you see "Cannot open
      display", run with:  xvfb-run -a python xfoil_paneling_test.py ...
"""

import os
import re
import sys
import shutil
import tempfile
import subprocess


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
XFOIL_PATH = os.environ.get("XFOIL_PATH", shutil.which("xfoil") or "xfoil")
DEFAULT_RE = 200_000
DEFAULT_ALPHA = 5.0
TIMEOUT = 60  # seconds per run


# ---------------------------------------------------------------------------
# Coordinate loading (mirrors your parser's cleaning: strip header, CRLF, etc.)
# ---------------------------------------------------------------------------
def load_clean_coords(path):
    with open(path, "r") as f:
        raw = f.readlines()

    coords = []
    for line in raw:
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
        if -0.5 <= x <= 1.5 and -1.0 <= y <= 1.0:
            coords.append((x, y))
    return coords


def write_coords(coords, path, name="AIRFOIL"):
    with open(path, "w", newline="\n") as f:
        f.write(name + "\n")
        for x, y in coords:
            f.write(f"{x:.6f}  {y:.6f}\n")


# ---------------------------------------------------------------------------
# Strategy command builders
# Each returns a list of XFOIL command lines (graphics already disabled).
# ---------------------------------------------------------------------------
def graphics_off():
    # PLOP -> G toggles graphics, blank line exits the PLOP menu
    return ["PLOP", "G", ""]


def strat_baseline(coords_file, reynolds, alpha, cp_file):
    return graphics_off() + [
        f"LOAD {coords_file}",
        "PANE",
        "OPER",
        f"VISC {int(reynolds)}",
        "ITER 500",
        f"ALFA {alpha}",
        f"CPWR {cp_file}",
        "",
        "QUIT",
    ]


def strat_alfa_step(coords_file, reynolds, alpha, cp_file):
    return graphics_off() + [
        f"LOAD {coords_file}",
        "PANE",
        "OPER",
        f"VISC {int(reynolds)}",
        "ITER 500",
        "ALFA 0",          # establish converged BL first
        f"ALFA {alpha}",   # then step to target
        f"CPWR {cp_file}",
        "",
        "QUIT",
    ]


def strat_ppar_160(coords_file, reynolds, alpha, cp_file):
    # PPAR menu: N sets number of panels. Blank lines exit sub-prompts/menu.
    return graphics_off() + [
        f"LOAD {coords_file}",
        "PPAR",
        "N 160",
        "",                # accept / return from N prompt
        "",                # exit PPAR menu
        "PANE",
        "OPER",
        f"VISC {int(reynolds)}",
        "ITER 500",
        "ALFA 0",
        f"ALFA {alpha}",
        f"CPWR {cp_file}",
        "",
        "QUIT",
    ]


def strat_ppar_220_le(coords_file, reynolds, alpha, cp_file):
    # Denser paneling (220) plus increased LE/TE point bunching via T.
    return graphics_off() + [
        f"LOAD {coords_file}",
        "PPAR",
        "N 220",
        "T 1.5",           # bunch points toward LE/TE (default ~0.15-1.0)
        "",
        "",
        "PANE",
        "OPER",
        f"VISC {int(reynolds)}",
        "ITER 500",
        "ALFA 0",
        f"ALFA {alpha}",
        f"CPWR {cp_file}",
        "",
        "QUIT",
    ]


STRATEGIES = [
    ("baseline (LOAD->PANE->ALFA target)", strat_baseline),
    ("alfa_step (ALFA 0 then target)", strat_alfa_step),
    ("ppar_160 (160 panels + alfa step)", strat_ppar_160),
    ("ppar_220_le (220 panels, dense LE)", strat_ppar_220_le),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_xfoil(script_lines, work_dir):
    script = "\n".join(script_lines) + "\n"
    try:
        proc = subprocess.run(
            [XFOIL_PATH],
            input=script,
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=TIMEOUT,
        )
        return proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except FileNotFoundError:
        print(f"ERROR: XFOIL not found at '{XFOIL_PATH}'.")
        print("Install XFOIL or set XFOIL_PATH, then retry.")
        sys.exit(1)


def extract_coeffs(stdout):
    out = {}
    for key, pat in {
        "CL": r"CL\s*=\s*([-+]?\d*\.?\d+)",
        "CD": r"CD\s*=\s*([-+]?\d*\.?\d+)",
        "CM": r"Cm\s*=\s*([-+]?\d*\.?\d+)",
    }.items():
        m = re.findall(pat, stdout)
        if m:
            out[key] = float(m[-1])
    return out


def converged(stdout):
    # Heuristics: VISCAL convergence messages, or a final low rms line
    if "VISCAL:  Convergence failed" in stdout:
        return False
    if re.search(r"rms:\s*0\.\d+E-0[4-9]", stdout):
        return True
    if "Convergence achieved" in stdout:
        return True
    # Fall back to: did we get a CL out at the target?
    return bool(extract_coeffs(stdout))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    dat_path = sys.argv[1]
    reynolds = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_RE
    alpha = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_ALPHA

    if not os.path.exists(dat_path):
        print(f"File not found: {dat_path}")
        sys.exit(1)

    coords = load_clean_coords(dat_path)
    print("=" * 64)
    print(f"File:     {dat_path}")
    print(f"Points:   {len(coords)}")
    print(f"Reynolds: {int(reynolds)}")
    print(f"Alpha:    {alpha}")
    print(f"XFOIL:    {XFOIL_PATH}")
    print("=" * 64)

    if len(coords) < 10:
        print("Too few coordinates parsed — file may be malformed.")
        sys.exit(1)

    work_dir = tempfile.mkdtemp(prefix="xfoil_test_")
    coords_file = "coords.dat"
    write_coords(coords, os.path.join(work_dir, coords_file))

    results = []
    for label, builder in STRATEGIES:
        cp_file = f"cp_{label.split()[0]}.txt"
        cp_path = os.path.join(work_dir, cp_file)
        if os.path.exists(cp_path):
            os.remove(cp_path)

        script = builder(coords_file, reynolds, alpha, cp_file)
        stdout, stderr, rc = run_xfoil(script, work_dir)

        conv = converged(stdout)
        coeffs = extract_coeffs(stdout)
        cp_written = os.path.exists(cp_path) and os.path.getsize(cp_path) > 0

        results.append((label, conv, coeffs, cp_written))

        print(f"\n--- {label} ---")
        print(f"    converged   : {conv}")
        print(f"    Cp written  : {cp_written}")
        if coeffs:
            cl = coeffs.get("CL", "?")
            cd = coeffs.get("CD", "?")
            cm = coeffs.get("CM", "?")
            print(f"    CL={cl}  CD={cd}  CM={cm}")
        if "Excessive panel angle" in stdout:
            m = re.search(r"Excessive panel angle\s+([\d.]+)", stdout)
            ang = m.group(1) if m else "?"
            print(f"    note        : XFOIL warned of excessive LE panel angle ({ang} deg)")
        if stderr and "TIMEOUT" in stderr:
            print(f"    note        : TIMED OUT after {TIMEOUT}s")

    print("\n" + "=" * 64)
    print("SUMMARY")
    print("=" * 64)
    first_ok = None
    for label, conv, coeffs, cp in results:
        status = "OK " if (conv and cp) else "FAIL"
        print(f"  [{status}] {label}")
        if conv and cp and first_ok is None:
            first_ok = label
    print("-" * 64)
    if first_ok:
        print(f"First working strategy: {first_ok}")
        print("Use the corresponding command sequence in main.py.")
    else:
        print("No strategy succeeded. Try a higher Reynolds number or lower")
        print("alpha to confirm XFOIL works at all on this airfoil, then")
        print("re-run. If even that fails, the issue is environmental")
        print("(e.g. XFOIL needs a virtual display: use xvfb-run).")

    print(f"\nWork dir kept for inspection: {work_dir}")


if __name__ == "__main__":
    main()
