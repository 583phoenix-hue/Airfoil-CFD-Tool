#!/usr/bin/env python3
"""
airfoil_parser_benchmark.py
===========================

The (to our knowledge) largest open benchmark of airfoil coordinate-file
robustness for XFOIL analysis. It downloads the full public UIUC Airfoil
Coordinate Database (~1,600 airfoils) and, optionally, an Airfoil Tools
mirror, then measures TWO things for every airfoil:

    1. RAW XFOIL          : does stock XFOIL accept the file as-is and converge?
    2. AeroLab + XFOIL    : does the file converge after AeroLab's parser
                            cleans/normalises the coordinates first?

The difference between the two is the "uplift" delivered by the parser — i.e.
how many real-world airfoil files AeroLab rescues that raw XFOIL cannot use.

This is the reproducible reference material referenced in the AeroLab JOSS
paper. Running it regenerates the headline compliance statistics.

--------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------
    # full run (downloads UIUC, runs both raw and parsed, writes results)
    python airfoil_parser_benchmark.py

    # quick smoke test on the first 25 airfoils
    python airfoil_parser_benchmark.py --limit 25

    # use an already-downloaded folder of .dat files
    python airfoil_parser_benchmark.py --local-dir ./my_dat_files

    # change the test condition
    python airfoil_parser_benchmark.py --reynolds 500000 --alpha 4

OUTPUTS
    benchmark_results.csv   one row per airfoil with both outcomes
    benchmark_summary.json  aggregate percentages (the headline numbers)
    benchmark_summary.txt   human-readable report

--------------------------------------------------------------------------
REQUIREMENTS
--------------------------------------------------------------------------
    - XFOIL installed and on PATH (or set XFOIL_PATH)
    - Python 3.9+
    - requests   (pip install requests)
    - Your AeroLab main.py in the same folder (for the parser functions).
      The script imports parse_dat_file + detect_and_merge_sections from it.
      If it can't import them, it falls back to a bundled copy so the
      benchmark still runs standalone.
    - On Linux, run under a virtual display if XFOIL needs one:
          xvfb-run -a python airfoil_parser_benchmark.py
"""

import os
import re
import sys
import csv
import json
import time
import zipfile
import argparse
import tempfile
import subprocess
import urllib.request
from io import BytesIO
from datetime import datetime, timezone


# ===========================================================================
# Config
# ===========================================================================
XFOIL_PATH = os.environ.get("XFOIL_PATH", "xfoil")
UIUC_ZIP_URLS = [
    "https://m-selig.ae.illinois.edu/ads/archives/coord_seligFmt.zip",
    "https://m-selig.web.engr.illinois.edu/ads/archives/coord_seligFmt.zip",
]
DEFAULT_RE = 200_000
DEFAULT_ALPHA = 5.0
PER_RUN_TIMEOUT = 30          # seconds per XFOIL invocation
DOWNLOAD_TIMEOUT = 120        # seconds for the zip download


# ===========================================================================
# Parser import — prefer the real AeroLab parser, fall back to a local copy
# ===========================================================================
def load_parser():
    """
    Returns (parse_dat_file, detect_and_merge_sections).

    Tries to import from the user's main.py so the benchmark measures the
    ACTUAL shipped parser. Falls back to a bundled re-implementation that
    matches AeroLab's logic so the script still runs anywhere.
    """
    try:
        sys.path.insert(0, os.getcwd())
        from main import parse_dat_file, detect_and_merge_sections  # type: ignore
        print("[parser] Using parse functions imported from main.py")
        return parse_dat_file, detect_and_merge_sections
    except Exception as e:
        print(f"[parser] Could not import from main.py ({e}); using bundled copy.")
        return _bundled_parse_dat_file, _bundled_detect_and_merge_sections


# --- Bundled fallback implementation (mirrors AeroLab's parser) -------------
def _bundled_parse_dat_file(file_path):
    with open(file_path, "r", errors="ignore") as f:
        lines = f.readlines()

    data = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):          # UIUC comment lines
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            continue                    # header / non-numeric line
        # Skip Lednicer count line like "61. 61." or "20. 20."
        if abs(x) > 1.5 or abs(y) > 1.5:
            continue
        data.append([x, y])

    if len(data) < 10:
        raise ValueError(f"Too few coordinate points parsed ({len(data)})")
    return _bundled_detect_and_merge_sections(data)


def _bundled_detect_and_merge_sections(data_lines):
    x_coords = [p[0] for p in data_lines]
    section_break = None
    for i in range(1, len(data_lines)):
        if x_coords[i] < 0.01 and x_coords[i - 1] > 0.5:
            section_break = i
            break

    if section_break is not None:
        upper = data_lines[:section_break]
        lower = data_lines[section_break:]
        if upper[0][0] > upper[-1][0]:
            upper = list(reversed(upper))
        upper = list(reversed(upper))
        if lower[0][0] > lower[-1][0]:
            lower = list(reversed(lower))
        if lower and abs(lower[0][0]) < 0.001 and abs(lower[0][1]) < 0.001:
            lower = lower[1:]
        merged = upper + lower
    else:
        if x_coords[0] > 0.99 and x_coords[-1] > 0.99:
            le_idx = x_coords.index(min(x_coords))
            if le_idx > 0 and data_lines[le_idx - 1][1] > 0:
                merged = data_lines
            elif le_idx > 0:
                merged = list(reversed(data_lines))
            else:
                merged = data_lines
        else:
            merged = data_lines
    # NOTE: closed trailing edge is preserved (the NACA 6-series fix)
    return merged


# ===========================================================================
# Data acquisition
# ===========================================================================
def download_uiuc(dest_dir):
    """Download and extract the UIUC Selig-format zip into dest_dir/*.dat."""
    os.makedirs(dest_dir, exist_ok=True)
    for url in UIUC_ZIP_URLS:
        try:
            print(f"[download] Fetching UIUC archive: {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "AeroLab-Benchmark/1.0"})
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                blob = resp.read()
            if len(blob) < 10_000:
                print("   archive suspiciously small, trying next mirror")
                continue
            with zipfile.ZipFile(BytesIO(blob)) as zf:
                members = [m for m in zf.namelist() if m.lower().endswith(".dat")]
                for m in members:
                    name = os.path.basename(m)
                    if not name:
                        continue
                    with zf.open(m) as src, open(os.path.join(dest_dir, name), "wb") as out:
                        out.write(src.read())
            print(f"[download] Extracted {len(members)} .dat files to {dest_dir}")
            return True
        except Exception as e:
            print(f"   failed: {e}")
    return False


UIUC_COORD_BASE_URLS = [
    "https://m-selig.ae.illinois.edu/ads/coord/",
    "https://m-selig.web.engr.illinois.edu/ads/coord/",
]
COORD_REQUEST_DELAY = 0.5  # seconds between requests — be polite to their server


def download_uiuc_coord_individual(dest_dir, name_source_dir, limit=0):
    """
    Download .dat files individually from the UIUC 'coord/' directory — the
    same directory linked from the public A-Z listing that real users
    browse and copy-paste from. This is distinct from the coord_seligFmt.zip
    archive: the zip appears to be a normalised re-export, while coord/
    contains the original per-airfoil files, some in Selig format and some
    in Lednicer format, with varying cleanliness.

    The list of filenames to fetch is reused from an already-downloaded zip
    (name_source_dir) so we don't need to scrape the A-Z HTML page first.

    A small delay is added between requests to avoid hammering the server.
    """
    os.makedirs(dest_dir, exist_ok=True)
    names = [os.path.basename(p) for p in collect_dat_files(name_source_dir)]
    if limit:
        names = names[:limit]

    # Skip anything already downloaded — only fetch what's missing. Without
    # this, re-running with a higher --limit would needlessly re-download
    # every file from scratch instead of just the new ones.
    already_have = {os.path.basename(p) for p in collect_dat_files(dest_dir)}
    to_fetch = [n for n in names if n not in already_have]
    skipped = len(names) - len(to_fetch)
    if skipped:
        print(f"[download] {skipped} files already present in {dest_dir}, skipping those")
    if not to_fetch:
        print("[download] Nothing new to fetch — all requested files already downloaded.")
        return True
    names = to_fetch

    base_url = None
    # Test connectivity using a name from the FULL original list, not just
    # the missing ones — if every missing file happens to be unavailable
    # under that exact name (e.g. renamed/removed upstream), testing with
    # names[0] from `to_fetch` would wrongly report total mirror failure.
    probe_candidates = names[:1] if names else []
    full_names = [os.path.basename(p) for p in collect_dat_files(name_source_dir)]
    if full_names:
        probe_candidates = [full_names[0]] + probe_candidates

    for candidate in UIUC_COORD_BASE_URLS:
        reached = False
        for probe_name in probe_candidates:
            try:
                test_url = candidate + probe_name
                req = urllib.request.Request(test_url, headers={"User-Agent": "AeroLab-Benchmark/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        reached = True
                        break
            except Exception:
                continue
        if reached:
            base_url = candidate
            break
    if base_url is None:
        print("[download] Could not reach the coord/ directory on any mirror.")
        return False

    print(f"[download] Fetching {len(names)} individual files from {base_url}")
    print(f"[download] (≈{len(names) * COORD_REQUEST_DELAY / 60:.1f} min at "
          f"{COORD_REQUEST_DELAY}s/request — this is intentionally slow to be polite)")

    ok, failed = 0, 0
    for i, name in enumerate(names, 1):
        url = base_url + name
        out_path = os.path.join(dest_dir, name)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AeroLab-Benchmark/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                content = resp.read()
            with open(out_path, "wb") as f:
                f.write(content)
            ok += 1
        except Exception:
            failed += 1
        if i % 50 == 0 or i == len(names):
            print(f"  [{i:4d}/{len(names)}] downloaded={ok}  failed={failed}")
        time.sleep(COORD_REQUEST_DELAY)

    print(f"[download] Done: {ok} downloaded, {failed} failed -> {dest_dir}")
    return ok > 0


def collect_dat_files(folder):
    files = []
    for root, _dirs, names in os.walk(folder):
        for n in names:
            if n.lower().endswith(".dat"):
                files.append(os.path.join(root, n))
    return sorted(files)


def count_le_passes(coords, le_thresh=0.05, te_thresh=0.90):
    """
    Count how many times the coordinate trace descends from near the trailing
    edge to near the leading edge and returns. A normal single-element airfoil
    does this exactly once. Multi-element configurations (e.g. the 30P-30N
    slat/main/flap high-lift system) do it two or more times, because each
    element is a separate closed loop in the file.
    """
    passes = 0
    state = "start"
    for x, _y in coords:
        if x <= le_thresh and state in ("start", "high"):
            state = "low"
        elif x >= te_thresh and state == "low":
            passes += 1
            state = "high"
    return passes


def is_multi_element(coords):
    """
    True if the file appears to contain more than one airfoil element.
    XFOIL is a single-element panel code and cannot analyse these, so they
    are reported as a separate 'out of scope' category rather than counted
    as parser failures.
    """
    return count_le_passes(coords) >= 2


# ===========================================================================
# XFOIL execution
# ===========================================================================
def write_coords(coords, path, name="AIRFOIL"):
    with open(path, "w", newline="\n") as f:
        f.write(name + "\n")
        for x, y in coords:
            f.write(f"{x:.6f}  {y:.6f}\n")


def run_xfoil(coords_filename, work_dir, reynolds, alpha):
    """
    Run a single viscous XFOIL point. Returns (converged: bool, cl: float|None).
    Graphics disabled via PLOP/G so it never blocks on a display.
    """
    cp_file = "cp_bench.txt"
    cp_path = os.path.join(work_dir, cp_file)
    if os.path.exists(cp_path):
        os.remove(cp_path)

    script = "\n".join([
        "PLOP", "G", "",
        f"LOAD {coords_filename}",
        "PANE",
        "OPER",
        f"VISC {int(reynolds)}",
        "ITER 200",
        "ALFA 0",
        f"ALFA {alpha}",
        f"CPWR {cp_file}",
        "",
        "QUIT",
    ]) + "\n"

    try:
        proc = subprocess.run(
            [XFOIL_PATH], input=script, capture_output=True,
            text=True, cwd=work_dir, timeout=PER_RUN_TIMEOUT,
        )
        out = proc.stdout
    except subprocess.TimeoutExpired:
        return False, None
    except FileNotFoundError:
        print(f"FATAL: XFOIL not found at '{XFOIL_PATH}'. Set XFOIL_PATH.")
        sys.exit(1)

    # Convergence heuristics
    if "VISCAL:  Convergence failed" in out:
        return False, None
    cp_ok = os.path.exists(cp_path) and os.path.getsize(cp_path) > 0
    cl = None
    m = re.findall(r"CL\s*=\s*([-+]?\d*\.?\d+)", out)
    if m:
        cl = float(m[-1])
    converged = cp_ok and (cl is not None)
    return converged, cl


def test_raw(dat_path, work_dir, reynolds, alpha):
    """Copy the file verbatim and hand it straight to XFOIL (no parsing)."""
    raw_name = "raw_input.dat"
    with open(dat_path, "r", errors="ignore") as src:
        content = src.read()
    with open(os.path.join(work_dir, raw_name), "w", newline="\n") as out:
        out.write(content)
    return run_xfoil(raw_name, work_dir, reynolds, alpha)


def test_parsed(dat_path, work_dir, reynolds, alpha, parse_fn):
    """Run the file through AeroLab's parser, then hand the result to XFOIL."""
    coords = parse_fn(dat_path)            # may raise on truly broken files
    write_coords(coords, os.path.join(work_dir, "parsed_input.dat"))
    return run_xfoil("parsed_input.dat", work_dir, reynolds, alpha)


# ===========================================================================
# Main benchmark loop
# ===========================================================================
def main():
    ap = argparse.ArgumentParser(description="AeroLab airfoil parser benchmark")
    ap.add_argument("--local-dir", help="Folder of .dat files to use instead of downloading")
    ap.add_argument("--limit", type=int, default=0, help="Only test the first N airfoils")
    ap.add_argument("--reynolds", type=float, default=DEFAULT_RE)
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--out-prefix", default="benchmark")
    ap.add_argument(
        "--source", choices=["zip", "coord"], default="zip",
        help="'zip' = coord_seligFmt.zip bulk archive (default, fast, one "
             "request). 'coord' = download each file individually from the "
             "ads/coord/ directory — the same files linked from the public "
             "A-Z listing that real users browse and copy-paste from. This "
             "is the messier, less-normalised source; slower (one request "
             "per airfoil, rate-limited) but tests the format your parser "
             "actually targets.",
    )
    args = ap.parse_args()

    parse_dat_file, _ = load_parser()

    # --- get the data ------------------------------------------------------
    if args.local_dir:
        data_dir = args.local_dir
        if not os.path.isdir(data_dir):
            print(f"--local-dir not found: {data_dir}")
            sys.exit(1)
    elif args.source == "coord":
        # The individual coord/ directory needs a filename list. Reuse the
        # zip download (cached if already present) purely as a name index —
        # we then re-download each file individually from coord/ so the
        # ACTUAL content tested is the individual-file version, not the zip's.
        zip_cache_dir = os.path.join(tempfile.gettempdir(), "uiuc_airfoils")
        if not collect_dat_files(zip_cache_dir):
            if not download_uiuc(zip_cache_dir):
                print("Could not download the zip to build the filename list.")
                sys.exit(1)

        data_dir = os.path.join(tempfile.gettempdir(), "uiuc_airfoils_coord")
        existing = collect_dat_files(data_dir)
        wanted_count = args.limit if args.limit else len(collect_dat_files(zip_cache_dir))
        if len(existing) < wanted_count:
            ok = download_uiuc_coord_individual(data_dir, zip_cache_dir, limit=args.limit)
            if not ok:
                print("Could not download from coord/. Try --source zip or --local-dir.")
                sys.exit(1)
    else:
        data_dir = os.path.join(tempfile.gettempdir(), "uiuc_airfoils")
        if not collect_dat_files(data_dir):
            ok = download_uiuc(data_dir)
            if not ok:
                print("Could not download UIUC database. Use --local-dir instead.")
                sys.exit(1)

    files = collect_dat_files(data_dir)
    if args.limit:
        files = files[:args.limit]
    print(f"[benchmark] Testing {len(files)} airfoils at "
          f"Re={int(args.reynolds)}, alpha={args.alpha}  (source={args.source})\n")


    base_work_dir = tempfile.mkdtemp(prefix="bench_")
    rows = []
    counts = {
        "total": 0,
        "multi_element": 0,    # detected multi-element configs (out of XFOIL scope)
        "raw_converged": 0,
        "parsed_converged": 0,
        "rescued": 0,          # raw failed, parsed succeeded
        "regressed": 0,        # raw succeeded, parsed failed (should be ~0)
        "both_failed": 0,
        "parser_errored": 0,   # parser raised an exception
    }

    t0 = time.time()
    interrupted = False
    try:
        for idx, dat in enumerate(files, 1):
            name = os.path.splitext(os.path.basename(dat))[0]
            counts["total"] += 1

            # Each airfoil gets its own fresh subfolder, exactly like AeroLab's
            # production backend (one uuid-named work_dir per request). This
            # rules out any chance of stale files or XFOIL state bleeding
            # between iterations of this loop, which a single shared work_dir
            # could not guarantee.
            work_dir = os.path.join(base_work_dir, f"run_{idx:05d}")
            os.makedirs(work_dir, exist_ok=True)

            # --- multi-element detection ---------------------------------------
            # XFOIL cannot analyse multi-element (slat/main/flap) configurations,
            # so detect them up front and record separately. They are excluded
            # from the single-element convergence percentages below.
            multi = False
            try:
                probe_coords = parse_dat_file(dat)
                multi = is_multi_element(probe_coords)
            except Exception:
                # If the parser can't read it at all, fall through to the normal
                # path; it will be recorded as a parser error there.
                probe_coords = None

            if multi:
                counts["multi_element"] += 1
                rows.append({
                    "airfoil": name,
                    "multi_element": True,
                    "raw_converged": "",
                    "raw_CL": "",
                    "parsed_converged": "",
                    "parsed_CL": "",
                    "parser_error": "",
                })
                if idx % 25 == 0 or idx == len(files):
                    elapsed = time.time() - t0
                    rate = idx / elapsed if elapsed else 0
                    eta = (len(files) - idx) / rate if rate else 0
                    print(f"  [{idx:4d}/{len(files)}] "
                          f"raw={counts['raw_converged']:4d}  "
                          f"parsed={counts['parsed_converged']:4d}  "
                          f"rescued={counts['rescued']:4d}  "
                          f"multi={counts['multi_element']:3d}  "
                          f"(ETA {eta/60:.1f} min)")
                continue

            raw_ok, raw_cl = False, None
            try:
                raw_ok, raw_cl = test_raw(dat, work_dir, args.reynolds, args.alpha)
            except Exception as e:
                # A single unexpected failure (I/O error, encoding issue, etc.)
                # must not crash the whole run and lose all progress — record
                # it as a raw failure and continue.
                print(f"  WARNING: raw test crashed on {name}: {str(e)[:100]}")

            parsed_ok = False
            parsed_cl = None
            parser_error = ""
            try:
                parsed_ok, parsed_cl = test_parsed(dat, work_dir, args.reynolds,
                                                   args.alpha, parse_dat_file)
            except Exception as e:
                parser_error = str(e)[:120]
                counts["parser_errored"] += 1

            if raw_ok:
                counts["raw_converged"] += 1
            if parsed_ok:
                counts["parsed_converged"] += 1
            if (not raw_ok) and parsed_ok:
                counts["rescued"] += 1
            if raw_ok and (not parsed_ok):
                counts["regressed"] += 1
            if (not raw_ok) and (not parsed_ok):
                counts["both_failed"] += 1

            rows.append({
                "airfoil": name,
                "multi_element": False,
                "raw_converged": raw_ok,
                "raw_CL": f"{raw_cl:.4f}" if raw_cl is not None else "",
                "parsed_converged": parsed_ok,
                "parsed_CL": f"{parsed_cl:.4f}" if parsed_cl is not None else "",
                "parser_error": parser_error,
            })

            if idx % 25 == 0 or idx == len(files):
                elapsed = time.time() - t0
                rate = idx / elapsed if elapsed else 0
                eta = (len(files) - idx) / rate if rate else 0
                print(f"  [{idx:4d}/{len(files)}] "
                      f"raw={counts['raw_converged']:4d}  "
                      f"parsed={counts['parsed_converged']:4d}  "
                      f"rescued={counts['rescued']:4d}  "
                      f"multi={counts['multi_element']:3d}  "
                      f"(ETA {eta/60:.1f} min)")

    except KeyboardInterrupt:
        interrupted = True
        print(f"\n[benchmark] Interrupted by user at airfoil {counts['total']}/{len(files)}. "
              f"Writing partial results so far...")
    except Exception as e:
        interrupted = True
        print(f"\n[benchmark] Unexpected error after {counts['total']}/{len(files)} airfoils: {e}")
        print("[benchmark] Writing partial results collected so far...")

    if not rows:
        print("[benchmark] No results were collected — nothing to write.")
        sys.exit(1)

    # --- write outputs -----------------------------------------------------
    csv_path = f"{args.out_prefix}_results.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    # Percentages are computed over SINGLE-ELEMENT airfoils only, since
    # multi-element configs are out of XFOIL's scope and would otherwise
    # understate both raw and parsed convergence rates equally.
    single_element_total = counts["total"] - counts["multi_element"]

    def pct(n):
        return round(100.0 * n / single_element_total, 2) if single_element_total else 0.0

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "reynolds": int(args.reynolds),
        "alpha": args.alpha,
        "xfoil_path": XFOIL_PATH,
        "total_airfoils": counts["total"],
        "multi_element_excluded": counts["multi_element"],
        "single_element_evaluated": single_element_total,
        "raw_xfoil_converged": counts["raw_converged"],
        "raw_xfoil_converged_pct": pct(counts["raw_converged"]),
        "aerolab_converged": counts["parsed_converged"],
        "aerolab_converged_pct": pct(counts["parsed_converged"]),
        "rescued_by_parser": counts["rescued"],
        "rescued_by_parser_pct": pct(counts["rescued"]),
        "uplift_pct_points": round(pct(counts["parsed_converged"])
                                   - pct(counts["raw_converged"]), 2),
        "regressed": counts["regressed"],
        "both_failed": counts["both_failed"],
        "parser_errored": counts["parser_errored"],
    }
    with open(f"{args.out_prefix}_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    report = f"""\
================================================================
AeroLab Airfoil Parser Benchmark — Summary
================================================================
Generated : {summary['generated_utc']}
Condition : Re = {summary['reynolds']:,}   alpha = {summary['alpha']} deg

Airfoils total            : {summary['total_airfoils']}
Multi-element (excluded)  : {summary['multi_element_excluded']}
Single-element evaluated  : {summary['single_element_evaluated']}

RAW XFOIL (file as-is)
    converged : {summary['raw_xfoil_converged']}  ({summary['raw_xfoil_converged_pct']} %)

AEROLAB PARSER + XFOIL
    converged : {summary['aerolab_converged']}  ({summary['aerolab_converged_pct']} %)

HEADLINE RESULT
    Files rescued by parser : {summary['rescued_by_parser']}  ({summary['rescued_by_parser_pct']} %)
    Convergence uplift      : +{summary['uplift_pct_points']} percentage points

Diagnostics
    Regressed (raw ok, parsed failed) : {summary['regressed']}
    Both failed                       : {summary['both_failed']}
    Parser raised an error            : {summary['parser_errored']}
================================================================
Full per-airfoil results: {csv_path}
"""
    with open(f"{args.out_prefix}_summary.txt", "w") as f:
        f.write(report)
    print("\n" + report)


if __name__ == "__main__":
    main()