import subprocess
import os
import re
import platform
import time
import uuid
import shutil
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from anyio import to_thread
from typing import Optional

# Aeroelasticity modules are still under active development and aren't
# necessarily committed to every deployment yet. Import them defensively so a
# missing module just disables the /aeroelasticity/* endpoints (they return
# 503 below) instead of crashing the whole app at startup -- previously an
# unconditional import here meant ANY deploy without these three files failed
# to boot at all, taking down the working XFOIL endpoints along with them.
try:
    import static_divergence as aero_div
    import control_reversal as aero_rev
    import flutter_vg as aero_flutter
    AEROELASTICITY_AVAILABLE = True
except ImportError:
    aero_div = aero_rev = aero_flutter = None
    AEROELASTICITY_AVAILABLE = False

# Inverse design (same defensive pattern): only needs inverse_design.py +
# numpy/scipy and the stock XFOIL binary.
try:
    import inverse_design as inv_design
    INVERSE_DESIGN_AVAILABLE = True
except ImportError:
    inv_design = None
    INVERSE_DESIGN_AVAILABLE = False

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

if not AEROELASTICITY_AVAILABLE:
    logger.warning(
        "Aeroelasticity modules (static_divergence/control_reversal/flutter_vg) "
        "not found -- /aeroelasticity/* endpoints will return 503"
    )

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Student Airfoil CFD Tool")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "HEAD"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 1 * 1024 * 1024
MAX_POINTS    = 500
MIN_POINTS    = 10
MIN_REYNOLDS  = 1e4
MAX_REYNOLDS  = 1e7
MIN_ALPHA     = -10
MAX_ALPHA     = 20
MIN_NCRIT     = 0.1
MAX_NCRIT     = 20.0
MAX_MACH      = 0.75  # XFOIL's Karman-Tsien correction becomes unreliable
                      # beyond this as shock effects appear, which a panel
                      # method cannot capture at all
VALID_MODES   = {"viscous", "inviscid"}

xfoil_semaphore = asyncio.Semaphore(3)

import tempfile

if platform.system() == "Windows":
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil.exe")
    IS_WINDOWS = True
    # Was os.getcwd(), which on a typical dev machine is the project
    # folder itself -- a real problem when that folder is synced by
    # OneDrive (or Dropbox/Google Drive), since the sync client can
    # grab a transient lock on newly created/written files, causing
    # intermittent PermissionError on exactly this kind of rapid
    # create-write-delete work-directory pattern. Confirmed directly
    # (WinError 13 on divergence_script.txt) rather than assumed.
    # tempfile.gettempdir() resolves to the real OS temp directory
    # (e.g. AppData\Local\Temp), outside any sync client's scope.
    TMP_DIR = tempfile.gettempdir()
else:
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil")
    IS_WINDOWS = False
    TMP_DIR = "/tmp"

STALE_WORKDIR_PREFIXES = ("run_", "aero_div_", "aero_rev_", "aero_flt_", "inverse_")
STALE_WORKDIR_MAX_AGE_SECONDS = 3600  # 1 hour


def _cleanup_stale_work_dirs():
    """
    Safety net for the rare case a work directory survives its own
    request-level cleanup (each endpoint's finally block already calls
    shutil.rmtree with ignore_errors=True, which means a deletion that
    fails -- e.g. a file transiently locked by antivirus at that exact
    moment -- fails silently rather than retrying). Runs once at
    startup and removes any of this app's own work directories older
    than STALE_WORKDIR_MAX_AGE_SECONDS, so leftovers from a crashed or
    interrupted run don't just accumulate indefinitely. Only touches
    directories matching this app's own naming prefixes, in TMP_DIR --
    never a broad temp-folder sweep.
    """
    if not os.path.isdir(TMP_DIR):
        return
    now = time.time()
    removed = 0
    try:
        for name in os.listdir(TMP_DIR):
            if not name.startswith(STALE_WORKDIR_PREFIXES):
                continue
            path = os.path.join(TMP_DIR, name)
            if not os.path.isdir(path):
                continue
            try:
                age = now - os.path.getmtime(path)
                if age > STALE_WORKDIR_MAX_AGE_SECONDS:
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Stale work-dir cleanup scan failed: {e}")
        return
    if removed:
        logger.info(f"Startup cleanup: removed {removed} stale work director"
                    f"{'y' if removed == 1 else 'ies'} older than "
                    f"{STALE_WORKDIR_MAX_AGE_SECONDS // 60} minutes")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _cleanup_stale_work_dirs()
    yield


app.router.lifespan_context = _lifespan


def _tokenize_coord_line(stripped: str):
    """
    Parse one coordinate line into (x, y), trying formats in order:
      1. Whitespace-separated, period decimals (existing/standard case)
      2. Comma-separated, period decimals (CSV export, e.g. "0.5,0.02")
      3. Whitespace-separated, comma decimals (European locale export,
         e.g. "0,5 0,02" — common from CAD tools set to a European locale)
    Returns (x, y) or None if no format matches. Only the first two tokens
    are used, so a stray 3rd column (e.g. z=0 from a 3D export) is already
    harmless without any special-casing.
    """
    # 1. Whitespace-separated, period decimals
    parts = stripped.split()
    if len(parts) >= 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass

    # 2. Comma-separated, period decimals (CSV export)
    if "," in stripped:
        csv_parts = [p.strip() for p in stripped.split(",") if p.strip()]
        if len(csv_parts) >= 2:
            try:
                return float(csv_parts[0]), float(csv_parts[1])
            except ValueError:
                pass

    # 3. Whitespace-separated, comma decimals (European locale)
    if len(parts) >= 2:
        try:
            return float(parts[0].replace(",", ".")), float(parts[1].replace(",", "."))
        except ValueError:
            pass

    return None


def parse_dat_file(file_path: str):
    """
    Parse airfoil coordinates from .dat file.
    Returns a tuple: (coords, fixes) where fixes is a list of human-readable
    strings describing each repair applied, for display in the frontend.
    """
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()

        fixes = []
        raw_pairs = []          # every successfully-tokenized (x, y), unfiltered
        used_csv_separator = False
        used_decimal_comma = False
        skipped_non_coord = 0
        explicit_split = None   # set below if a Lednicer point-count header is found

        # --- Lednicer point-count header detection (BEFORE anything else) --
        # A Lednicer-format file's second line (after the title) is a pair
        # of point counts, e.g. "44.  44.", NOT a coordinate. Both tokens
        # are valid floats, so without this check it silently enters
        # raw_pairs as a real point (44.0, 44.0) -- and since that's larger
        # than any genuine normalized chord coordinate, it was single-
        # handedly triggering the "absolute units" rescale below (dividing
        # every real point by 44), corrupting the whole geometry into a
        # sliver near the origin while the bogus header point became
        # exactly (1.0, 1.0) and got kept as if it were real. Reproduced
        # directly on a real UIUC file (fx711530.dat, Lednicer format,
        # "44.  44." header) which XFOIL then choked on downstream
        # ("SOPPS: Opposite-point location failed", "LEFIND: LE point not
        # found", eventually a real BL-array overflow on the resulting
        # degenerate, over-refined shape) -- none of that was a real
        # accuracy/array-size problem, it was this corrupted input.
        nonblank = [l.strip() for l in lines if l.strip()]
        if len(nonblank) >= 2:
            header_pair = _tokenize_coord_line(nonblank[1])
            if header_pair is not None:
                hv1, hv2 = header_pair
                looks_like_counts = (
                    hv1 > 1.5 and hv2 > 1.5
                    and abs(hv1 - round(hv1)) < 1e-6
                    and abs(hv2 - round(hv2)) < 1e-6
                )
                if looks_like_counts:
                    nu, nl = int(round(hv1)), int(round(hv2))
                    remaining = len(nonblank) - 2   # everything after title + count line
                    if abs(remaining - (nu + nl)) <= 1:
                        explicit_split = nu
                        lines = [nonblank[0]] + nonblank[2:]  # drop the count-header line
                        fixes.append(
                            f"Lednicer point-count header detected ({nu} + {nl} points) "
                            f"and excluded from coordinate data"
                        )

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Track which fallback format actually matched, for the fixes log
            whitespace_parts = stripped.split()
            plain_ok = False
            if len(whitespace_parts) >= 2:
                try:
                    float(whitespace_parts[0]); float(whitespace_parts[1])
                    plain_ok = True
                except ValueError:
                    plain_ok = False

            pair = _tokenize_coord_line(stripped)
            if pair is None:
                skipped_non_coord += 1
                continue

            if not plain_ok:
                if "," in stripped and len(whitespace_parts) < 2:
                    used_csv_separator = True
                elif len(whitespace_parts) >= 2:
                    used_decimal_comma = True

            raw_pairs.append(list(pair))

        if used_csv_separator:
            fixes.append("Comma-separated (CSV) coordinate lines detected and parsed")
        if used_decimal_comma:
            fixes.append("European decimal-comma format detected and converted")

        # --- Unit-scale normalization -----------------------------------
        # A normalized airfoil's x should span roughly 0 to 1 (the chord).
        # Files exported from general CAD tools sometimes carry absolute
        # units instead (e.g. a 250 mm chord exported as x in [0, 250]).
        # Detect this from the RAW unfiltered data (before the range filter
        # below would otherwise silently drop every point as "out of
        # range") and rescale by the max |x| so the shape survives.
        max_abs_x = max((abs(p[0]) for p in raw_pairs), default=0.0)
        if max_abs_x > 3.0:
            scale = 1.0 / max_abs_x
            raw_pairs = [[x * scale, y * scale] for x, y in raw_pairs]
            fixes.append(
                f"Coordinates rescaled to normalized chord (detected absolute "
                f"units, max |x| = {max_abs_x:.2f}, scaled by 1/{max_abs_x:.2f})"
            )

        # --- Range filter (applied AFTER any rescaling above) -----------
        data_lines = []
        skipped_out_of_range = 0
        for x, y in raw_pairs:
            if -0.5 <= x <= 1.5 and -1.0 <= y <= 1.0:
                data_lines.append([x, y])
            else:
                skipped_out_of_range += 1

        if skipped_non_coord > 0:
            fixes.append(f"Non-coordinate lines skipped: {skipped_non_coord} header/comment line(s) removed")
        if skipped_out_of_range > 0:
            fixes.append(f"Out-of-range points filtered: {skipped_out_of_range} point(s) outside valid bounds removed")

        if len(data_lines) < 10:
            raise HTTPException(status_code=400,
                detail=f"Insufficient valid coordinates. Found {len(data_lines)} points.")

        coords, geom_fixes = detect_and_merge_sections(data_lines, explicit_split=explicit_split)
        fixes.extend(geom_fixes)

        if not fixes:
            fixes = ["No changes made — file was already in valid Selig format"]

        return coords, fixes

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")


def detect_and_merge_sections(data_lines, explicit_split=None):
    """
    Detect format and merge if needed.
    Returns (coords, fixes) where fixes is a list of repair descriptions.

    explicit_split: if the caller already knows the true upper/lower point
    counts (from a Lednicer point-count header line -- see parse_dat_file),
    pass the upper-section length here to use it directly instead of the
    x_coords-crossing heuristic below. The heuristic is a reasonable guess
    for files with no header, but it's guesswork; a real header is ground
    truth and should win whenever it's still consistent with the data
    actually in hand (it may not be, e.g. if range-filtering dropped a
    point earlier -- guarded below).
    """
    fixes = []
    x_coords = [pt[0] for pt in data_lines]
    section_break = None
    if explicit_split is not None and 0 < explicit_split < len(data_lines):
        section_break = explicit_split
    else:
        for i in range(1, len(data_lines)):
            if x_coords[i] < 0.01 and x_coords[i-1] > 0.5:
                section_break = i
                break

    if section_break is not None:
        upper = data_lines[:section_break]
        lower = data_lines[section_break:]
        logger.debug(f"Lednicer format: {len(upper)} upper, {len(lower)} lower")
        fixes.append(
            f"Lednicer format detected and converted: two-section format "
            f"({len(upper)} upper + {len(lower)} lower points) merged into "
            f"a single Selig-format loop for XFOIL"
        )
        # Ensure upper goes LE->TE first, then reverse to TE->LE for XFOIL
        if upper[0][0] > upper[-1][0]:
            upper = list(reversed(upper))
        upper = list(reversed(upper))
        # Ensure lower goes LE->TE
        if lower[0][0] > lower[-1][0]:
            lower = list(reversed(lower))
        # Both sections share the LE point (0,0) — remove duplicate from lower
        if lower and abs(lower[0][0]) < 0.001 and abs(lower[0][1]) < 0.001:
            lower = lower[1:]
            fixes.append("Duplicate leading-edge point removed from Lednicer lower section")
            logger.debug("Removed duplicate LE point from Lednicer lower section")
        merged = upper + lower
    else:
        logger.debug(f"Single section: {len(data_lines)} points")
        if x_coords[0] > 0.99 and x_coords[-1] > 0.99:
            le_idx = x_coords.index(min(x_coords))
            if le_idx > 0:
                point_before_le_y = data_lines[le_idx - 1][1]
                if point_before_le_y > 0:
                    logger.debug("TE-to-TE format, correct order (TE->upper->LE->lower->TE)")
                    merged = data_lines
                else:
                    logger.debug("TE-to-TE format, reversing (was TE->lower->LE->upper->TE)")
                    merged = list(reversed(data_lines))
                    fixes.append(
                        "Winding order corrected: coordinates were in reversed order "
                        "(TE→lower→LE→upper→TE) and have been reversed to the correct "
                        "Selig order (TE→upper→LE→lower→TE)"
                    )
            else:
                merged = data_lines
        else:
            merged = data_lines

    # NOTE: Do NOT strip a coincident first/last point here.
    # For a Selig-format airfoil the coordinate list is a single closed loop
    # that legitimately starts and ends at the same trailing-edge point
    # (common in NACA 6-series files, e.g. both ends at 1.00000 0.00000).
    # Removing that final point opens the trailing edge, producing a large
    # TE gap that XFOIL reports as a "Blunt trailing edge" and then fails to
    # converge on. XFOIL handles a closed loop correctly, so we keep it.
    return merged, fixes


def parse_polar_coefficients(polar_path: str):
    """
    Fallback parser for XFOIL's PACC polar-accumulation save file.

    Unlike console output, this file always gets a numeric data row written
    on every ALFA solve regardless of viscous/inviscid mode, so it's used
    as a fallback when console-text CL/CD/Cm extraction comes up empty
    (observed with some XFOIL builds in pure inviscid mode, which solves
    without an iteration-convergence report and so never echoes "CL =").

    Row format (whitespace-separated): alpha  CL  CD  CDp  CM  [Top_Xtr Bot_Xtr]
    Returns a coefficients dict or None if the file is missing/unparseable.
    """
    if not os.path.exists(polar_path):
        return None
    try:
        with open(polar_path, "r") as f:
            lines = f.readlines()
    except Exception:
        return None

    data_rows = []
    header_passed = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("---"):
            header_passed = True
            continue
        if not header_passed or not stripped:
            continue
        parts = stripped.split()
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if len(vals) >= 5:
            data_rows.append(vals)

    if not data_rows:
        return None

    last = data_rows[-1]  # final/converged row
    return {"CL": last[1], "CD": last[2], "CDp": last[3], "Cm": last[4]}


def _polar_has_alpha(polar_path: str, alpha: float) -> bool:
    """True if XFOIL's PACC polar file has a (converged) row at this alpha."""
    if not os.path.exists(polar_path):
        return False
    header_passed = False
    with open(polar_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("---"):
                header_passed = True
                continue
            if not header_passed or not stripped:
                continue
            try:
                vals = [float(p) for p in stripped.split()]
            except ValueError:
                continue
            if len(vals) >= 5 and abs(vals[0] - alpha) < 1e-3:
                return True
    return False


def extract_aerodynamic_coefficients(stdout: str):
    """Extract coefficients — takes last occurrence (final converged value)."""
    coefficients = {}
    patterns = {
        "CL":  r"CL\s*=\s*([-+]?\d*\.?\d+)",
        "CD":  r"CD\s*=\s*([-+]?\d*\.?\d+)",
        "CDp": r"CDp\s*=\s*([-+]?\d*\.?\d+)",
        "Cm":  r"Cm\s*=\s*([-+]?\d*\.?\d+)",
    }
    for key, pattern in patterns.items():
        matches = re.findall(pattern, stdout)
        if matches:
            coefficients[key] = float(matches[-1])
    return coefficients


def parse_bl_dump(bl_file_path: str):
    """
    Parse XFOIL DUMP output file.

    XFOIL DUMP column order (8 columns):
        s   x   y   Ue/Vinf   Dstar   Theta   Cf   H

    File structure: one continuous block, ordered by arc length s:
        TE -> (over the top) -> LE -> (under the bottom) -> TE -> wake points (x > 1)
    NOTE: earlier versions of this parser assumed a blank line separated the
    upper and lower surface sections. XFOIL's DUMP output does not actually
    include that separator, so that split silently produced 0 lower-surface
    points on every run. We now split at the leading edge (minimum x) instead,
    and drop trailing wake points (x > 1, past the trailing edge) so they
    don't get folded into the lower surface.

    Returns None if file is missing or cannot be parsed.
    """
    if not os.path.exists(bl_file_path):
        logger.info(f"BL dump file not found: {bl_file_path}")
        return None

    combined = []

    try:
        with open(bl_file_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                parts = stripped.split()
                if len(parts) < 7:
                    continue
                try:
                    vals = [float(p) for p in parts[:7]]
                except ValueError:
                    continue
                H = float(parts[7]) if len(parts) >= 8 else None
                combined.append({
                    "x":     vals[1],
                    "y":     vals[2],
                    "dstar": vals[4],
                    "theta": vals[5],
                    "cf":    vals[6],
                    "H":     H,
                })

        if not combined:
            logger.info("BL parse: no data rows found in dump file")
            return None

        # Leading edge = point of minimum x. Points before/at it (TE -> LE)
        # are the upper surface; points after it, up to x ~= 1.0 (back at the
        # TE), are the lower surface. Anything beyond that (x > 1) is wake.
        le_idx = min(range(len(combined)), key=lambda i: combined[i]["x"])
        upper_rows = combined[:le_idx + 1]

        lower_rows = []
        for row in combined[le_idx + 1:]:
            if row["x"] <= 1.0 + 1e-6:
                lower_rows.append(row)
            else:
                break  # wake points start here

        logger.info(f"BL parse: {len(upper_rows)} upper pts, {len(lower_rows)} lower pts")

        def find_transition_x(rows):
            if len(rows) < 4:
                return None
            for i in range(1, len(rows) - 1):
                prev_cf = abs(rows[i - 1]["cf"])
                curr_cf = abs(rows[i]["cf"])
                if prev_cf > 1e-6 and curr_cf > 1e-6 and (curr_cf / prev_cf) > 2.5:
                    return rows[i]["x"]
            return None

        tr_upper = find_transition_x(upper_rows)
        tr_lower = find_transition_x(lower_rows)

        logger.info(f"BL parse: transition upper x={tr_upper}, lower x={tr_lower}")

        return {
            "upper":              upper_rows,
            "lower":              lower_rows,
            "transition_upper_x": tr_upper,
            "transition_lower_x": tr_lower,
        }

    except Exception as e:
        logger.info(f"BL parse error: {e}")
        return None


def ramp_angles(alpha: float):
    """Warm-start angles for the ramp strategy: 0 deg towards the target in
    steps of at most 2.5 deg (target excluded), or None if |alpha| < 1.
    XFOIL converges far more reliably when each solution starts from the
    previous angle's (e.g. Clark Y, Re 500k, 5 deg fails from a cold start in
    XFOIL 6.996 but converges via 0 and 2.5). Same as rampAngles() in the
    browser solver (aerolab-web/src/lib/xfoil/analysis.js)."""
    import math as _m
    n = _m.ceil(abs(alpha) / 2.5)
    if n < 1 or abs(alpha) < 1:
        return None
    return [round(alpha * i / n, 3) for i in range(n)]


def run_xfoil_sync(
    coords_file:    str,
    reynolds:       float,
    alpha:          float,
    work_dir:       str,
    ncrit:          float = 9.0,
    force_inviscid: bool = False,
    mach:           float = 0.0,
):
    """
    Run XFOIL with retry strategy. Returns (cp_x, cp_values, coefficients, bl_data).

    If force_inviscid is True (user explicitly selected Inviscid mode), the
    viscous strategies are skipped entirely and XFOIL is run once in inviscid
    mode — no retry needed since there's no convergence to fall back from.
    """
    coords_filename = "airfoil.dat"
    cp_filename     = "cp_output.txt"
    bl_filename     = "bl_output.txt"

    shutil.copy(coords_file, os.path.join(work_dir, coords_filename))

    if force_inviscid:
        logger.info("INVISCID mode explicitly requested — skipping viscous strategies")
        return _run_xfoil_mode(coords_filename, cp_filename, bl_filename, work_dir,
                               reynolds, alpha, viscous=False, timeout=20, smooth_geometry=False,
                               ncrit=ncrit, mach=mach)

    # Strategy 1: Viscous, warm-started from 0 deg (when |alpha| >= 1)
    ramp = ramp_angles(alpha)
    if ramp:
        try:
            logger.info(f"Attempt 1: VISCOUS mode, warm start via {ramp} (NCrit={ncrit})...")
            return _run_xfoil_mode(coords_filename, cp_filename, bl_filename, work_dir,
                                   reynolds, alpha, viscous=True, timeout=90, smooth_geometry=False,
                                   ncrit=ncrit, mach=mach, ramp=ramp)
        except subprocess.TimeoutExpired:
            logger.error("Viscous warm-start mode timed out after 90s")
        except Exception as e:
            logger.info(f"Warm-start strategy failed: {e}")

    # Strategy 2: Viscous, clean geometry, cold start
    try:
        logger.info(f"Attempt 2: VISCOUS mode, clean geometry (NCrit={ncrit})...")
        return _run_xfoil_mode(coords_filename, cp_filename, bl_filename, work_dir,
                               reynolds, alpha, viscous=True, timeout=90, smooth_geometry=False,
                               ncrit=ncrit, mach=mach)
    except subprocess.TimeoutExpired:
        logger.error("Viscous mode timed out after 90s")
    except Exception as e:
        # Catch ALL xfoil solver failures so we always fall through to next strategy.
        logger.info(f"Cold-start strategy failed: {e}")

    # Strategy 3: Viscous, smoothed geometry
    try:
        logger.info(f"Attempt 3: VISCOUS mode, smoothed geometry (NCrit={ncrit})...")
        return _run_xfoil_mode(coords_filename, cp_filename, bl_filename, work_dir,
                               reynolds, alpha, viscous=True, timeout=90, smooth_geometry=True,
                               ncrit=ncrit, mach=mach)
    except subprocess.TimeoutExpired:
        logger.error("Viscous mode with smoothing timed out")
    except Exception as e:
        logger.info(f"Smoothed-geometry strategy failed: {e}")

    # Strategy 4: Inviscid fallback (no BL data)
    sep = "=" * 70
    logger.info(sep)
    logger.warning("FALLING BACK TO INVISCID MODE")
    logger.info("BL data will NOT be available in inviscid mode")
    logger.info(sep)
    try:
        return _run_xfoil_mode(coords_filename, cp_filename, bl_filename, work_dir,
                               reynolds, alpha, viscous=False, timeout=20, smooth_geometry=False,
                               ncrit=ncrit, mach=mach)
    except Exception as e:
        raise Exception(f"All strategies failed. Last error: {e}")


def _run_xfoil_mode(
    coords_filename: str,
    cp_filename:     str,
    bl_filename:     str,
    work_dir:        str,
    reynolds:        float,
    alpha:           float,
    viscous:         bool,
    timeout:         int,
    smooth_geometry: bool = False,
    ncrit:           float = 9.0,
    mach:            float = 0.0,
    ramp:            Optional[list] = None,
):
    cp_out_path    = os.path.abspath(os.path.join(work_dir, cp_filename))
    bl_out_path    = os.path.abspath(os.path.join(work_dir, bl_filename))
    polar_filename = "polar_output.txt"
    polar_out_path = os.path.abspath(os.path.join(work_dir, polar_filename))
    script_path    = os.path.abspath(os.path.join(work_dir, "xfoil_script.txt"))
    log_path       = os.path.abspath(os.path.join(work_dir, "xfoil_output.log"))

    for path in [cp_out_path, bl_out_path, polar_out_path, log_path]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    # Graphics off: XFOIL then needs no X display, the same as the inverse
    # design and aeroelasticity runs.
    script_lines = ["PLOP", "G", ""]
    script_lines.append(f"LOAD {coords_filename}")
    script_lines.append("PANE")

    if smooth_geometry:
        script_lines.append("GDES")
        script_lines.append("SMOO")
        script_lines.append("")

    script_lines.append("OPER")

    if mach and mach > 0:
        script_lines.append(f"MACH {mach}")

    if viscous:
        script_lines.append(f"VISC {int(reynolds)}")
        script_lines.append("ITER 500")
        script_lines.append("VPAR")
        script_lines.append(f"N {ncrit}")
        script_lines.append("")
        # Warm-up angles (not accumulated in the polar file)
        for a_warm in (ramp or []):
            script_lines.append(f"ALFA {a_warm}")

    # Polar accumulation: XFOIL always writes a numeric CL/CD/CDp/Cm row here
    # on every ALFA solve, viscous or inviscid — unlike the console printout,
    # which only echoes a "CL =" summary line as part of the viscous
    # iteration-convergence report. This is our robust fallback source.
    # IMPORTANT: must be opened AFTER viscous mode is established above —
    # opening it while still in the default inviscid state left the polar
    # accumulator's internal mode stuck, producing CD-forced-to-0 rows and
    # broken (asymmetric) BL dumps even on solves that should converge fine.
    script_lines.append("PACC")
    script_lines.append(polar_filename)
    script_lines.append("")

    script_lines.append(f"ALFA {alpha}")
    script_lines.append(f"CPWR {cp_filename}")

    if viscous:
        script_lines.append(f"DUMP {bl_filename}")

    script_lines.append("PACC")  # toggle accumulation off before quitting

    script_lines.append("")
    script_lines.append("QUIT")

    with open(script_path, "w", newline="\n") as f:
        f.write("\n".join(script_lines))

    # Fixed f-strings: extract expressions to variables first
    mode = "VISCOUS" if viscous else "INVISCID"
    smooth_str = "+ SMOOTH" if smooth_geometry else ""
    sep70 = "=" * 70
    logger.info("\n" + sep70)
    ncrit_str = f", NCrit={ncrit}" if viscous else ""
    logger.info(f"XFOIL SCRIPT ({mode}{smooth_str}{ncrit_str})")
    logger.info(sep70)
    for i, line in enumerate(script_lines):
        logger.info(f"  {i+1:2d}: {repr(line)}")
    logger.info(sep70)

    proc = None
    try:
        with open(script_path, "r") as script_file:
            proc = subprocess.Popen(
                [XFOIL_EXE],
                stdin=script_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=work_dir,
            )

        stdout, stderr = proc.communicate(timeout=timeout)
        time.sleep(0.3)

        with open(log_path, "w", newline="\n") as f:
            f.write("=" * 70 + "\n")
            f.write(f"XFOIL LOG ({mode})\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Reynolds:    {reynolds}\n")
            f.write(f"Alpha:       {alpha}\n")
            f.write(f"Viscous:     {viscous}\n")
            f.write(f"NCrit:       {ncrit if viscous else 'N/A'}\n")
            f.write(f"Return code: {proc.returncode}\n\n")
            f.write("STDOUT\n" + "=" * 70 + "\n")
            f.write(stdout)
            f.write("\n\nSTDERR\n" + "=" * 70 + "\n")
            f.write(stderr)

        logger.info(f"Return code: {proc.returncode}")
        if proc.returncode != 0:
            logger.warning(f"Non-zero exit code: {proc.returncode}")

        panel_matches = re.findall(r"Number of panel nodes\s+(\d+)", stdout)
        if panel_matches:
            panel_count = int(panel_matches[-1])
            logger.info(f"Detected: {panel_count} panels")
            if panel_count >= 140:
                logger.info(f"Panel count is sufficient for accurate results")
            else:
                logger.warning(f"Low panel count ({panel_count})")
        else:
            logger.warning(f"Could not detect panel count")
            logger.info(f"   XFOIL may have crashed early")

        if viscous:
            visc_confirmed = any(ind in stdout for ind in ["Re =", "VISCAL", "Cm ="])
            if visc_confirmed and ("CDp" in stdout or "CD =" in stdout):
                logger.info("Viscous mode confirmed")
            else:
                logger.warning("Viscous mode requested but may not have converged")
                logger.info("   Results may be inviscid or unconverged")

        if ramp:
            # Warm-up angles may print failures of their own; the target angle
            # converged iff it made it into the polar file (XFOIL only
            # accumulates converged points).
            convergence_failed = not _polar_has_alpha(polar_out_path, alpha)
        else:
            convergence_failed = (
                "VISCAL:  Convergence failed" in stdout or
                "not converged" in stdout.lower() or
                "unconverged" in stdout.lower()
            )
        if convergence_failed:
            raise Exception(f"Viscous convergence failed at alpha={alpha}")

        if not os.path.exists(cp_out_path):
            logger.info(f"Last 800 chars: {stdout[-800:]}")
            raise Exception(f"{mode} did not generate CP output file")

        coefficients = extract_aerodynamic_coefficients(stdout)
        if (not coefficients or "CL" not in coefficients) and not viscous:
            # Only trust the polar-file fallback for genuine inviscid runs.
            # In viscous mode, a missing console "CL =" line means the BL
            # iteration did NOT converge — the polar file may still contain
            # a garbage partial row (leftover inviscid CL, CD forced to 0).
            # We must let that raise below so run_xfoil_sync's retry cascade
            # (smoothed geometry, then true inviscid) can proceed instead of
            # silently "succeeding" with a bogus CD=0 result.
            logger.warning("Console CL parse failed — trying polar accumulation file fallback")
            polar_coefficients = parse_polar_coefficients(polar_out_path)
            if polar_coefficients and "CL" in polar_coefficients:
                logger.info(f"Recovered coefficients from polar file: {polar_coefficients}")
                coefficients = polar_coefficients

        if not coefficients or "CL" not in coefficients:
            logger.error(f"No coefficients extracted from XFOIL output")
            logger.info(f"RAW STDOUT (full, {len(stdout)} chars):\n{stdout}")
            logger.info(f"\nChecking if ALFA {alpha} was processed:")
            alpha_patterns = [
                f"alfa = {alpha:.3f}",
                f"ALFA   {alpha:.2f}",
                f"a = {alpha:.2f}",
            ]
            found_alpha = any(pattern.lower() in stdout.lower() for pattern in alpha_patterns)
            if found_alpha:
                logger.info(f"  Alpha command was processed")
            else:
                logger.info(f"  WARNING: Could not verify alpha={alpha} was calculated!")
                logger.info(f"  This suggests XFOIL may have used cached/stale results")
            raise Exception(f"No valid aerodynamic coefficients found for alpha={alpha}")

        cp_x, cp_values = [], []
        with open(cp_out_path, "r") as f:
            for line in f:
                clean = line.strip()
                if not clean or any(c.isalpha() for c in clean):
                    continue
                parts = clean.split()
                if len(parts) >= 2:
                    try:
                        # Cp is the LAST column: XFOIL 6.97 writes "x Cp",
                        # 6.99 (Windows build) writes "x y Cp".
                        cp_x.append(float(parts[0]))
                        cp_values.append(float(parts[-1]))
                    except ValueError:
                        continue

        if not cp_x:
            raise Exception("No pressure data")

        bl_data = None
        if viscous:
            bl_data = parse_bl_dump(bl_out_path)
            status = f"upper={len(bl_data['upper'])}, lower={len(bl_data['lower'])}" if bl_data else "not available"
            logger.info(f"BL data: {status}")

        cl = coefficients.get("CL", 0)
        cd = coefficients.get("CD", 0.0001)
        ld = cl / cd if cd > 0 else 0

        logger.info(f"CL={cl:.4f}  CD={cd:.6f}  L/D={ld:.1f}  CP_pts={len(cp_x)}")

        if cd < 0.005 and viscous and reynolds > 100000:
            logger.warning(f"CD={cd:.6f} seems low (expected 0.007-0.012)")
        if ld > 150:
            logger.warning(f"L/D={ld:.0f} unusually high")

        coefficients["mode"] = "viscous" if viscous else "inviscid"
        if viscous:
            coefficients["ncrit"] = ncrit
        if not viscous:
            coefficients["warning"] = "INVISCID MODE - CD is unrealistically low"

        return cp_x, cp_values, coefficients, bl_data

    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        raise
    except Exception as e:
        raise e


@app.get("/")
async def root(request: Request):
    return {"status": "ok", "service": "Airfoil CFD API (BL edition)"}


@app.head("/health")
@app.get("/health")
async def health(request: Request):
    xfoil_exists = os.path.exists(XFOIL_EXE) or (
        not IS_WINDOWS and os.system(f"which {XFOIL_EXE} >/dev/null 2>&1") == 0
    )
    return {
        "status":       "healthy" if xfoil_exists else "degraded",
        "xfoil_path":   XFOIL_EXE,
        "xfoil_exists": xfoil_exists,
        "platform":     platform.system(),
    }


@app.get("/analysis_count")
def analysis_count(request: Request):
    """
    Exposes the analysis counter over HTTP for frontends without direct DB
    access (e.g. a JS frontend). Requires db_utils.py to be importable from
    wherever this backend runs — if it isn't (or the DB isn't configured
    here), returns {"count": null} rather than failing the whole service.
    """
    try:
        from db_utils import get_analysis_count
        return {"count": get_analysis_count()}
    except Exception as e:
        logger.info(f"analysis_count unavailable: {e}")
        return {"count": None}


@app.post("/analysis_count/increment")
async def analysis_count_increment():
    """Analyses now run in the visitor's browser (XFOIL compiled to
    WebAssembly), so the page calls this after each one to keep the public
    counter going."""
    await _count_analysis_async()
    return {"ok": True}


@app.post("/upload_airfoil/")
async def upload_airfoil(
    request:  Request,
    file:     UploadFile,
    reynolds: float = Form(...),
    alpha:    float = Form(...),
    ncrit:    float = Form(9.0),
    mode:     str   = Form("viscous"),
    mach:     float = Form(0.0),
):
    if not (MIN_REYNOLDS <= reynolds <= MAX_REYNOLDS):
        raise HTTPException(status_code=400,
            detail=f"Reynolds must be {MIN_REYNOLDS:,.0f} to {MAX_REYNOLDS:,.0f}")
    if not (MIN_ALPHA <= alpha <= MAX_ALPHA):
        raise HTTPException(status_code=400,
            detail=f"Alpha must be {MIN_ALPHA} to {MAX_ALPHA} degrees")
    if not (MIN_NCRIT <= ncrit <= MAX_NCRIT):
        raise HTTPException(status_code=400,
            detail=f"NCrit must be {MIN_NCRIT} to {MAX_NCRIT}")
    if not (0.0 <= mach <= MAX_MACH):
        raise HTTPException(status_code=400,
            detail=f"Mach must be 0.0 to {MAX_MACH} (XFOIL's compressibility "
                   f"correction is not reliable beyond this)")
    mode = mode.strip().lower()
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400,
            detail=f"Mode must be one of {sorted(VALID_MODES)}")
    if not file.filename.endswith((".dat", ".txt")):
        raise HTTPException(status_code=400, detail="Only .dat or .txt files accepted")

    run_id   = str(uuid.uuid4())[:8]
    work_dir = os.path.join(TMP_DIR, f"run_{run_id}")
    os.makedirs(work_dir, exist_ok=True)

    raw_path = os.path.join(work_dir, "raw.dat")
    fix_path = os.path.join(work_dir, "airfoil_fixed.dat")

    # Fixed f-string: was logger.info(f"\n{"="*60}\n...")
    sep60 = "=" * 60
    logger.info(f"\n{sep60}\nNEW REQUEST: {file.filename}\nPlatform: {platform.system()}\n"
                f"Mode: {mode}  NCrit: {ncrit}\n{sep60}")

    try:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400,
                detail=f"File too large (max {MAX_FILE_SIZE/(1024*1024)}MB)")

        with open(raw_path, "wb") as f:
            f.write(content)

        raw_coords, parser_fixes = parse_dat_file(raw_path)
        if len(raw_coords) > MAX_POINTS:
            raise HTTPException(status_code=400, detail=f"Too many points (max {MAX_POINTS})")

        logger.info(f"Parsed: {len(raw_coords)} points, fixes: {parser_fixes}")

        with open(fix_path, "w") as f:
            f.write("AIRFOIL\n")
            for x, y in raw_coords:
                f.write(f"  {x:.6f}  {y:.6f}\n")

        async with xfoil_semaphore:
            cp_x, cp_values, coefficients, bl_data = await to_thread.run_sync(
                run_xfoil_sync, fix_path, reynolds, alpha, work_dir, ncrit, mode == "inviscid", mach
            )

        bl_response = None
        if bl_data is not None:
            bl_response = {
                "upper":              bl_data["upper"],
                "lower":              bl_data["lower"],
                "transition_upper_x": bl_data["transition_upper_x"],
                "transition_lower_x": bl_data["transition_lower_x"],
            }

        await to_thread.run_sync(_count_analysis)

        return {
            "success":       True,
            "coords_before": raw_coords,
            "coords_after":  raw_coords,
            "num_points":    len(raw_coords),
            "cp_x":          cp_x,
            "cp_values":     cp_values,
            "coefficients":  coefficients,
            "bl_data":       bl_response,
            "parser_fixes":  parser_fixes,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            if os.path.exists(work_dir):
                time.sleep(0.2)
                shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass



def _json_safe(obj):
    """Recursively replace NaN/inf (not valid JSON) with None and numpy
    scalars with plain Python numbers. Avoids importing numpy here so
    main.py still boots on a deployment without the aeroelasticity stack."""
    import math as _math
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()  # numpy scalar -> Python scalar
        except Exception:
            pass
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if _math.isfinite(obj) else None
    return obj


async def _prepare_aero_workdir(prefix: str, file: Optional[UploadFile]):
    """Create the work dir and, if a file was uploaded, run it through the
    same coordinate repair pipeline as the main analysis."""
    run_id = str(uuid.uuid4())[:8]
    work_dir = os.path.join(TMP_DIR, f"{prefix}{run_id}")
    os.makedirs(work_dir, exist_ok=True)
    seed_filename = None
    if file is not None and file.filename:
        content_bytes = await file.read()
        if len(content_bytes) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File too large")
        raw_path = os.path.join(work_dir, "raw.dat")
        with open(raw_path, "wb") as f:
            f.write(content_bytes)
        coords, _ = parse_dat_file(raw_path)
        seed_filename = "airfoil_fixed.dat"
        with open(os.path.join(work_dir, seed_filename), "w") as f:
            f.write("AIRFOIL\n")
            for x, y in coords:
                f.write(f"  {x:.6f}  {y:.6f}\n")
    return work_dir, seed_filename


def _cleanup_workdir(work_dir: str):
    try:
        if work_dir and os.path.exists(work_dir):
            time.sleep(0.2)
            shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass


def _validate_aero_common(reynolds: float, v_start: float, v_step: float, v_max: float, rho: float):
    if not AEROELASTICITY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Aeroelasticity module not available on this deployment")
    if not (MIN_REYNOLDS <= reynolds <= MAX_REYNOLDS):
        raise HTTPException(status_code=400,
            detail=f"Reynolds must be {MIN_REYNOLDS:,.0f} to {MAX_REYNOLDS:,.0f}")
    if v_start <= 0 or v_step <= 0 or v_max <= v_start:
        raise HTTPException(status_code=400,
            detail="Speed sweep needs 0 < 'from' < 'up to' and a positive step")
    if (v_max - v_start) / v_step > 5000:
        raise HTTPException(status_code=400, detail="Speed step too small for this range (max 5000 points)")
    if rho <= 0:
        raise HTTPException(status_code=400, detail="Air density must be positive")


def _aero_error(e: Exception, name: str):
    if AEROELASTICITY_AVAILABLE and isinstance(e, aero_div.XfoilPolarError):
        logger.warning(f"{name}: {e}")
        return HTTPException(status_code=422, detail=str(e))
    logger.error(f"{name}: {e}")
    return HTTPException(status_code=500, detail=str(e))


def _count_analysis():
    """Bump the public 'analyses run' counter; never fails the request."""
    try:
        from db_utils import increment_analysis_count
        increment_analysis_count()
    except Exception as e:
        logger.info(f"increment_analysis_count unavailable: {e}")


async def _count_analysis_async():
    # The database call blocks, so keep it off the event loop.
    await to_thread.run_sync(_count_analysis)


@app.post("/aeroelasticity/divergence")
async def aeroelasticity_divergence(
    request: Request,
    file: UploadFile = None,
    reynolds: float = Form(500000),
    ncrit: float = Form(9.0),
    alpha_root: float = Form(2.0),
    k_alpha: float = Form(2000.0),
    x_ea_over_c: float = Form(0.35),
    chord: float = Form(1.0),
    span: float = Form(1.0),
    rho: float = Form(1.225),
    v_start: float = Form(5.0),
    v_step: float = Form(5.0),
    v_max: float = Form(100.0),
):
    _validate_aero_common(reynolds, v_start, v_step, v_max, rho)
    if k_alpha <= 0 or chord <= 0 or span <= 0:
        raise HTTPException(status_code=400, detail="Stiffness, chord and span must be positive")
    if not (0.0 <= x_ea_over_c <= 1.0):
        raise HTTPException(status_code=400, detail="Elastic axis must be between 0 and 100% chord")

    work_dir = None
    try:
        work_dir, seed_filename = await _prepare_aero_workdir("aero_div_", file)
        async with xfoil_semaphore:
            result = await to_thread.run_sync(
                aero_div.analyze_divergence,
                work_dir, seed_filename, reynolds, ncrit,
                alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                v_start, v_step, v_max,
            )
        result["success"] = True
        await _count_analysis_async()
        return _json_safe(result)
    except HTTPException:
        raise
    except Exception as e:
        raise _aero_error(e, "aeroelasticity_divergence")
    finally:
        _cleanup_workdir(work_dir)


@app.post("/aeroelasticity/reversal")
async def aeroelasticity_reversal(
    request: Request,
    file: UploadFile = None,
    reynolds: float = Form(500000),
    ncrit: float = Form(9.0),
    alpha_root: float = Form(2.0),
    k_alpha: float = Form(2000.0),
    x_ea_over_c: float = Form(0.35),
    chord: float = Form(1.0),
    span: float = Form(1.0),
    rho: float = Form(1.225),
    flap_chord_fraction: float = Form(0.25),
    flap_source: str = Form("xfoil"),
    v_start: float = Form(2.0),
    v_step: float = Form(5.0),
    v_max: float = Form(100.0),
):
    _validate_aero_common(reynolds, v_start, v_step, v_max, rho)
    if k_alpha <= 0 or chord <= 0 or span <= 0:
        raise HTTPException(status_code=400, detail="Stiffness, chord and span must be positive")
    if not (0.0 <= x_ea_over_c <= 1.0):
        raise HTTPException(status_code=400, detail="Elastic axis must be between 0 and 100% chord")
    if not (0.05 <= flap_chord_fraction <= 0.6):
        raise HTTPException(status_code=400, detail="Flap chord fraction must be 0.05 to 0.6")
    if flap_source not in ("xfoil", "thin_airfoil"):
        raise HTTPException(status_code=400, detail="flap_source must be 'xfoil' or 'thin_airfoil'")

    work_dir = None
    try:
        work_dir, seed_filename = await _prepare_aero_workdir("aero_rev_", file)
        async with xfoil_semaphore:
            result = await to_thread.run_sync(
                lambda: aero_rev.analyze_reversal(
                    work_dir, seed_filename, reynolds, ncrit,
                    alpha_root, k_alpha, x_ea_over_c, chord, span, rho,
                    flap_chord_fraction, v_start, v_step, v_max,
                    flap_source=flap_source,
                )
            )
        result["success"] = True
        await _count_analysis_async()
        return _json_safe(result)
    except HTTPException:
        raise
    except Exception as e:
        raise _aero_error(e, "aeroelasticity_reversal")
    finally:
        _cleanup_workdir(work_dir)


@app.post("/aeroelasticity/flutter")
async def aeroelasticity_flutter(
    request: Request,
    file: UploadFile = None,
    reynolds: float = Form(500000),
    ncrit: float = Form(9.0),
    alpha_ref: float = Form(2.0),
    m: float = Form(38.49),
    mu: float = Form(8.082),
    xCG_percent: float = Form(55.0),
    xEA_percent: float = Form(45.0),
    kh: float = Form(9.621),
    ktheta: float = Form(9.621),
    chord: float = Form(2.0),
    rho: float = Form(1.225),
    use_real_airfoil_data: bool = Form(True),
    v_start: float = Form(0.1),
    v_step: float = Form(0.5),
    v_max: float = Form(100.0),
):
    _validate_aero_common(reynolds, v_start, v_step, v_max, rho)
    if min(m, mu, kh, ktheta, chord) <= 0:
        raise HTTPException(status_code=400, detail="Mass, inertia, stiffnesses and chord must be positive")
    if not (0.0 <= xCG_percent <= 100.0 and 0.0 <= xEA_percent <= 100.0):
        raise HTTPException(status_code=400, detail="CG and elastic axis must be between 0 and 100% chord")

    b = chord / 2.0
    xCG = (xCG_percent / 100.0 - 0.5) * chord
    xEA = (xEA_percent / 100.0 - 0.5) * chord

    work_dir = None
    try:
        work_dir, seed_filename = await _prepare_aero_workdir("aero_flt_", file)
        call = lambda: aero_flutter.analyze_flutter(
            work_dir, seed_filename, reynolds, ncrit, alpha_ref,
            m, mu, xCG, xEA, kh, ktheta, b, rho,
            use_real_airfoil_data=use_real_airfoil_data,
            U_start=v_start, U_step=v_step, U_max=v_max,
        )
        if use_real_airfoil_data:
            async with xfoil_semaphore:
                result = await to_thread.run_sync(call)
        else:
            result = await to_thread.run_sync(call)
        result.pop("history", None)  # legacy tuple form; "modes" carries it all
        result["success"] = True
        await _count_analysis_async()
        return _json_safe(result)
    except HTTPException:
        raise
    except Exception as e:
        raise _aero_error(e, "aeroelasticity_flutter")
    finally:
        _cleanup_workdir(work_dir)


# ─────────────────────────────────────────────────────────────────────────
# Inverse design (SU2-style Cp matching, see inverse_design.py)
# ─────────────────────────────────────────────────────────────────────────

async def _read_seed(file: Optional[UploadFile], work_dir: str):
    """Optional seed airfoil: repaired with the same parser as the main
    analysis. Returns coordinates or None (-> default NACA 0012)."""
    if file is None or not file.filename:
        return None
    content_bytes = await file.read()
    if len(content_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    raw_path = os.path.join(work_dir, "seed_raw.dat")
    with open(raw_path, "wb") as f:
        f.write(content_bytes)
    try:
        coords, _ = parse_dat_file(raw_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Couldn't read the seed airfoil: {e}")
    return coords


def _validate_inverse_common(reynolds: float, alpha: float, ncrit: float):
    if not INVERSE_DESIGN_AVAILABLE:
        raise HTTPException(status_code=503, detail="Inverse design module not available on this deployment")
    if not (MIN_REYNOLDS <= reynolds <= MAX_REYNOLDS):
        raise HTTPException(status_code=400,
            detail=f"Reynolds must be {MIN_REYNOLDS:,.0f} to {MAX_REYNOLDS:,.0f}")
    if not (MIN_ALPHA <= alpha <= MAX_ALPHA):
        raise HTTPException(status_code=400, detail=f"Alpha must be {MIN_ALPHA} to {MAX_ALPHA} degrees")
    if not (MIN_NCRIT <= ncrit <= MAX_NCRIT):
        raise HTTPException(status_code=400, detail=f"NCrit must be {MIN_NCRIT} to {MAX_NCRIT}")


@app.post("/inverse_design/baseline/")
async def inverse_design_baseline(
    request: Request,
    file: UploadFile = None,
    reynolds: float = Form(500000),
    alpha: float = Form(0.0),
    ncrit: float = Form(9.0),
):
    """Seed airfoil's own Cp at the chosen condition, sampled at the curve
    editor's points -- the starting curve the user then edits."""
    _validate_inverse_common(reynolds, alpha, ncrit)
    work_dir = os.path.join(TMP_DIR, f"inverse_{str(uuid.uuid4())[:8]}")
    os.makedirs(work_dir, exist_ok=True)
    try:
        seed = await _read_seed(file, work_dir)
        async with xfoil_semaphore:
            result = await to_thread.run_sync(
                lambda: inv_design.seed_baseline(work_dir, reynolds, alpha, seed, ncrit))
        result["success"] = True
        return _json_safe(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"inverse_design_baseline: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup_workdir(work_dir)


# Live progress of running inverse designs, keyed by a client-chosen job id.
# Single-process server, so a plain dict is enough; old entries are pruned.
INVERSE_PROGRESS = {}
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _set_inverse_progress(job_id, fraction, message):
    now = time.time()
    INVERSE_PROGRESS[job_id] = {"fraction": round(float(fraction), 3), "message": message, "t": now}
    for k in [k for k, v in INVERSE_PROGRESS.items() if now - v["t"] > 600]:
        INVERSE_PROGRESS.pop(k, None)


# Jobs the browser asked to stop (left the page, closed the tab, Cancel).
INVERSE_CANCELLED = {}


class InverseCancelled(Exception):
    pass


def _cancel_inverse(job_id):
    now = time.time()
    INVERSE_CANCELLED[job_id] = now
    for k in [k for k, t in INVERSE_CANCELLED.items() if now - t > 600]:
        INVERSE_CANCELLED.pop(k, None)


def _mp_context():
    """Process start method for inverse designs. Linux: a fork server that
    has inverse_design (numpy/scipy) preloaded, so each design starts fast and
    safely; Windows only has spawn."""
    import multiprocessing as mp
    if platform.system() == "Windows":
        return mp.get_context("spawn")
    ctx = mp.get_context("forkserver")
    ctx.set_forkserver_preload(["inverse_design"])
    return ctx


def _kill_job_process(p):
    import signal as _signal
    try:
        if hasattr(os, "killpg"):
            os.killpg(p.pid, _signal.SIGKILL)   # the job and any XFOIL it started
            return
    except Exception:
        pass
    try:
        p.kill()
    except Exception:
        pass


def _run_inverse_process(job_key, track, args, kwargs):
    """Run inv_design.run_inverse_design in a separate, lower-priority
    process (see run_inverse_design_job). Relays progress, and kills the
    process if the job is cancelled."""
    import queue as _queue
    ctx = _mp_context()
    q = ctx.Queue()
    p = ctx.Process(target=inv_design.run_inverse_design_job, args=(q, args, kwargs), daemon=True)
    p.start()
    finished = False
    try:
        while True:
            if job_key in INVERSE_CANCELLED:
                raise InverseCancelled()
            try:
                msg = q.get(timeout=0.5)
            except _queue.Empty:
                if p.is_alive():
                    continue
                try:
                    msg = q.get(timeout=1.0)
                except _queue.Empty:
                    raise RuntimeError(f"The design process stopped unexpectedly (exit code {p.exitcode}).")
            kind = msg[0]
            if kind == "progress":
                if track:
                    _set_inverse_progress(job_key, msg[1], msg[2])
                continue
            finished = True
            if kind == "done":
                return msg[1]
            if kind == "value_error":
                raise ValueError(msg[1])
            raise RuntimeError(msg[1])
    finally:
        if finished:
            p.join(timeout=5)
        if p.is_alive():
            _kill_job_process(p)
            p.join(timeout=5)
        q.close()
        q.cancel_join_thread()


@app.post("/inverse_design/cancel/{job_id}")
async def inverse_design_cancel(job_id: str):
    """Stop a running inverse design (the page calls this when you leave it,
    close the tab or press Cancel)."""
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    _cancel_inverse(job_id)
    return {"cancelled": True}


@app.get("/inverse_design/progress/{job_id}")
async def inverse_design_progress(job_id: str):
    """Progress of a running inverse design (fraction 0..1 and the current
    stage). Unknown / finished-and-expired ids return fraction 0."""
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    return INVERSE_PROGRESS.get(job_id, {"fraction": 0.0, "message": "Waiting for the solver", "t": None})


@app.post("/inverse_design/")
async def inverse_design_endpoint(
    request: Request,
    file: UploadFile = None,
    reynolds: float = Form(500000),
    alpha: float = Form(0.0),
    ncrit: float = Form(9.0),
    min_thickness_percent: float = Form(0.0),
    target_cp_upper: str = Form(...),
    target_cp_lower: str = Form(...),
    job_id: str = Form(""),
):
    """target_cp_upper/lower: JSON lists of [x/c, Cp]. file: optional seed
    airfoil (.dat, any format the main parser accepts); none -> NACA 0012."""
    import json as _json
    _validate_inverse_common(reynolds, alpha, ncrit)
    if not (0.0 <= min_thickness_percent <= 40.0):
        raise HTTPException(status_code=400, detail="Minimum thickness must be 0 to 40 % chord")
    try:
        tu = _json.loads(target_cp_upper)
        tl = _json.loads(target_cp_lower)
        if len(tu) < 3 or len(tl) < 3 or len(tu) > 500 or len(tl) > 500:
            raise ValueError("each surface needs 3 to 500 points")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid target curve: {e}")

    track = bool(job_id) and bool(_JOB_ID_RE.match(job_id))
    job_key = job_id if track else f"internal-{uuid.uuid4().hex}"
    if track:
        _set_inverse_progress(job_id, 0.0, "Waiting for the solver")
    work_dir = os.path.join(TMP_DIR, f"inverse_{str(uuid.uuid4())[:8]}")
    os.makedirs(work_dir, exist_ok=True)
    logger.info(f"INVERSE DESIGN: Re={reynolds} alpha={alpha} NCrit={ncrit} "
                f"min_t={min_thickness_percent}% seed={'upload' if file is not None and file.filename else 'NACA 0012'}")
    try:
        seed = await _read_seed(file, work_dir)
        async def _watch_disconnect():
            # Browser gone (tab closed, network lost) -> stop the job too.
            while True:
                await asyncio.sleep(2)
                if await request.is_disconnected():
                    _cancel_inverse(job_key)
                    return

        watcher = asyncio.create_task(_watch_disconnect())
        try:
            async with xfoil_semaphore:
                if job_key in INVERSE_CANCELLED:
                    raise InverseCancelled()
                result = await to_thread.run_sync(
                    _run_inverse_process, job_key, track,
                    (work_dir, reynolds, alpha, tu, tl),
                    dict(seed_coords=seed, ncrit=ncrit, min_thickness=min_thickness_percent / 100.0),
                )
        finally:
            watcher.cancel()
        await _count_analysis_async()
        result["success"] = True
        return _json_safe(result)
    except HTTPException:
        raise
    except InverseCancelled:
        logger.info(f"inverse_design: job {job_key} cancelled")
        raise HTTPException(status_code=409, detail="Design cancelled.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"inverse_design: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup_workdir(work_dir)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)