import subprocess
import os
import re
import platform
import time
import uuid
import shutil
import asyncio
from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from anyio import to_thread

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

xfoil_semaphore = asyncio.Semaphore(3)

if platform.system() == "Windows":
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil.exe")
    IS_WINDOWS = True
    TMP_DIR = os.getcwd()
else:
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil")
    IS_WINDOWS = False
    TMP_DIR = "/tmp"


def parse_dat_file(file_path: str):
    """Parse airfoil coordinates from .dat file."""
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
        data_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            try:
                x = float(parts[0])
                y = float(parts[1])
                if -0.5 <= x <= 1.5 and -1.0 <= y <= 1.0:
                    data_lines.append([x, y])
            except (ValueError, IndexError):
                continue
        if len(data_lines) < 10:
            raise HTTPException(status_code=400,
                detail=f"Insufficient valid coordinates. Found {len(data_lines)} points.")
        return detect_and_merge_sections(data_lines)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")


def detect_and_merge_sections(data_lines):
    """Detect format and merge if needed."""
    x_coords = [pt[0] for pt in data_lines]
    section_break = None
    for i in range(1, len(data_lines)):
        if x_coords[i] < 0.01 and x_coords[i-1] > 0.5:
            section_break = i
            break
    if section_break is not None:
        upper = data_lines[:section_break]
        lower = data_lines[section_break:]
        print(f"DEBUG: Lednicer format: {len(upper)} upper, {len(lower)} lower")
        if upper[0][0] < upper[-1][0]:
            upper = list(reversed(upper))
        if lower[0][0] > lower[-1][0]:
            lower = list(reversed(lower))
        merged = upper + lower
    else:
        print(f"DEBUG: Single section: {len(data_lines)} points")
        if x_coords[0] > 0.99 and x_coords[-1] > 0.99:
            le_idx = x_coords.index(min(x_coords))
            if le_idx + 1 < len(data_lines):
                point_after_le_y = data_lines[le_idx + 1][1]
                if point_after_le_y < 0:
                    print(f"DEBUG: TE-to-TE format, correct order (upper->LE->lower)")
                    merged = data_lines
                else:
                    print(f"DEBUG: TE-to-TE format, reversing (was lower->LE->upper)")
                    merged = list(reversed(data_lines))
            else:
                merged = data_lines
        else:
            merged = data_lines
    if len(merged) > 1 and abs(merged[0][0] - merged[-1][0]) < 0.001 and abs(merged[0][1] - merged[-1][1]) < 0.001:
        merged = merged[:-1]
        print(f"DEBUG: Removed duplicate TE")
    return merged


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

    File structure:
        Section 1 (before first blank line) : upper surface (TE to LE)
        Section 2 (after blank line)        : lower surface (LE to TE)

    Returns:
        {
            upper              : list of {x, y, dstar, theta, cf, H},
            lower              : list of {x, y, dstar, theta, cf, H},
            transition_upper_x : float or None,
            transition_lower_x : float or None,
        }
    Returns None if file is missing or cannot be parsed.
    """
    if not os.path.exists(bl_file_path):
        print(f"BL dump file not found: {bl_file_path}")
        return None

    sections      = []
    current_block = []

    try:
        with open(bl_file_path, "r") as f:
            for line in f:
                stripped = line.strip()

                # Blank line = section separator
                if not stripped:
                    if current_block:
                        sections.append(current_block)
                        current_block = []
                    continue

                parts = stripped.split()
                if len(parts) < 7:
                    continue   # skip header lines and short rows

                try:
                    vals = [float(p) for p in parts[:7]]
                except ValueError:
                    continue   # skip non-numeric lines

                # Column indices: 0=s, 1=x, 2=y, 3=Ue/Vinf, 4=Dstar, 5=Theta, 6=Cf
                H = float(parts[7]) if len(parts) >= 8 else None

                current_block.append({
                    "x":     vals[1],
                    "y":     vals[2],
                    "dstar": vals[4],
                    "theta": vals[5],
                    "cf":    vals[6],
                    "H":     H,
                })

        if current_block:
            sections.append(current_block)

        if not sections:
            print("BL parse: no sections found in dump file")
            return None

        upper_rows = sections[0] if len(sections) > 0 else []
        lower_rows = sections[1] if len(sections) > 1 else []

        print(f"BL parse: {len(upper_rows)} upper pts, {len(lower_rows)} lower pts")

        def find_transition_x(rows):
            """
            Detect laminar-to-turbulent transition by finding where Cf
            first jumps sharply (ratio > 2.5 over consecutive points).
            This is robust against leading-edge inviscid spikes.
            """
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

        print(f"BL parse: transition upper x={tr_upper}, lower x={tr_lower}")

        return {
            "upper":              upper_rows,
            "lower":              lower_rows,
            "transition_upper_x": tr_upper,
            "transition_lower_x": tr_lower,
        }

    except Exception as e:
        print(f"BL parse error: {e}")
        return None


def run_xfoil_sync(coords_file: str, reynolds: float, alpha: float, work_dir: str):
    """Run XFOIL with retry strategy. Returns (cp_x, cp_values, coefficients, bl_data)."""
    coords_filename = "airfoil.dat"
    cp_filename     = "cp_output.txt"
    bl_filename     = "bl_output.txt"

    shutil.copy(coords_file, os.path.join(work_dir, coords_filename))

    # Strategy 1: Viscous, clean geometry
    try:
        print("Attempt 1: VISCOUS mode, clean geometry...")
        return _run_xfoil_mode(coords_filename, cp_filename, bl_filename, work_dir,
                               reynolds, alpha, viscous=True, timeout=90, smooth_geometry=False)
    except subprocess.TimeoutExpired:
        print("ERROR: Viscous mode timed out after 90s")
    except Exception as e:
        if "convergence" in str(e).lower() or "no pressure data" in str(e).lower():
            print(f"Convergence issue: {e}")
        else:
            raise

    # Strategy 2: Viscous, smoothed geometry
    try:
        print("Attempt 2: VISCOUS mode, smoothed geometry...")
        return _run_xfoil_mode(coords_filename, cp_filename, bl_filename, work_dir,
                               reynolds, alpha, viscous=True, timeout=90, smooth_geometry=True)
    except subprocess.TimeoutExpired:
        print("ERROR: Viscous mode with smoothing timed out")
    except Exception as e:
        if "convergence" in str(e).lower() or "no pressure data" in str(e).lower():
            print(f"Smoothed geometry also failed: {e}")
        else:
            raise

    # Strategy 3: Inviscid fallback (no BL data)
    print("=" * 70)
    print("WARNING: FALLING BACK TO INVISCID MODE")
    print("BL data will NOT be available in inviscid mode")
    print("=" * 70)
    try:
        return _run_xfoil_mode(coords_filename, cp_filename, bl_filename, work_dir,
                               reynolds, alpha, viscous=False, timeout=20, smooth_geometry=False)
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
):
    """
    Linux-optimized XFOIL execution.

    XFOIL script — viscous, no smoothing:
    ───────────────────────────────────────────────
    LOAD airfoil.dat      load geometry
    PANE                  re-panel with default distribution
    OPER                  enter OPER menu
    VISC <Re>             enable viscous mode
    ITER 500              max Newton iterations
    ALFA <alpha>          solve at angle of attack
    CPWR cp_output.txt    write Cp output file
    DUMP bl_output.txt    write boundary layer dump (viscous only)
                          blank line — exits OPER menu (required)
    QUIT

    XFOIL script — viscous, with smoothing:
    ───────────────────────────────────────────────
    LOAD airfoil.dat
    PANE
    GDES                  enter geometry design menu
    SMOO                  smooth geometry
                          blank line — exits GDES menu
    OPER
    VISC <Re>
    ITER 500
    ALFA <alpha>
    CPWR cp_output.txt
    DUMP bl_output.txt
                          blank line — exits OPER menu
    QUIT

    XFOIL script — inviscid fallback:
    ───────────────────────────────────────────────
    LOAD airfoil.dat
    PANE
    OPER
    ALFA <alpha>
    CPWR cp_output.txt
                          blank line — exits OPER menu
    QUIT
    """

    cp_out_path = os.path.abspath(os.path.join(work_dir, cp_filename))
    bl_out_path = os.path.abspath(os.path.join(work_dir, bl_filename))
    script_path = os.path.abspath(os.path.join(work_dir, "xfoil_script.txt"))
    log_path    = os.path.abspath(os.path.join(work_dir, "xfoil_output.log"))

    # Remove stale output files
    for path in [cp_out_path, bl_out_path, log_path]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    # ── BUILD XFOIL SCRIPT ────────────────────────────────────────────────
    script_lines = []

    script_lines.append(f"LOAD {coords_filename}")  # load geometry
    script_lines.append("PANE")                      # re-panel

    if smooth_geometry:
        script_lines.append("GDES")                  # enter geometry design menu
        script_lines.append("SMOO")                  # smooth
        script_lines.append("")                      # exit GDES menu

    script_lines.append("OPER")                      # enter OPER menu

    if viscous:
        script_lines.append(f"VISC {int(reynolds)}") # enable viscous
        script_lines.append("ITER 500")              # iteration limit

    script_lines.append(f"ALFA {alpha}")             # solve at AoA
    script_lines.append(f"CPWR {cp_filename}")       # write Cp file

    if viscous:
        script_lines.append(f"DUMP {bl_filename}")   # write BL dump (viscous only)

    script_lines.append("")                          # exit OPER menu (required blank line)
    script_lines.append("QUIT")                     # exit XFOIL

    # Write with strict Unix line endings
    with open(script_path, "w", newline="\n") as f:
        f.write("\n".join(script_lines))

    mode = "VISCOUS" if viscous else "INVISCID"
    print(f"\n{"="*70}")
    print(f"XFOIL SCRIPT ({mode}{"+ SMOOTH" if smooth_geometry else ""})")
    print(f"{"="*70}")
    for i, line in enumerate(script_lines):
        print(f"  {i+1:2d}: {repr(line)}")
    print(f"{"="*70}\n")

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
            f.write(f"Return code: {proc.returncode}\n\n")
            f.write("STDOUT\n" + "=" * 70 + "\n")
            f.write(stdout)
            f.write("\n\nSTDERR\n" + "=" * 70 + "\n")
            f.write(stderr)

        print(f"Return code: {proc.returncode}")
        if proc.returncode != 0:
            print(f"Warning: Non-zero exit code: {proc.returncode}")

        panel_matches = re.findall(r"Number of panel nodes\s+(\d+)", stdout)
        if panel_matches:
            panel_count = int(panel_matches[-1])
            print(f"Panel count: {panel_count}")
            if panel_count < 140:
                print(f"Warning: Low panel count ({panel_count})")

        if viscous:
            visc_confirmed = any(ind in stdout for ind in ["Re =", "VISCAL", "Cm ="])
            if visc_confirmed and ("CDp" in stdout or "CD =" in stdout):
                print("Viscous mode confirmed")
            else:
                print("WARNING: Viscous mode may not have converged")

        convergence_failed = (
            "VISCAL:  Convergence failed" in stdout or
            "not converged" in stdout.lower() or
            "unconverged" in stdout.lower()
        )
        if convergence_failed:
            raise Exception(f"Viscous convergence failed at alpha={alpha}")

        if not os.path.exists(cp_out_path):
            print(f"Last 800 chars: {stdout[-800:]}")
            raise Exception(f"{mode} did not generate CP output file")

        coefficients = extract_aerodynamic_coefficients(stdout)
        if not coefficients or "CL" not in coefficients:
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
                        cp_x.append(float(parts[0]))
                        cp_values.append(float(parts[1]))
                    except ValueError:
                        continue

        if not cp_x:
            raise Exception("No pressure data")

        bl_data = None
        if viscous:
            bl_data = parse_bl_dump(bl_out_path)
            status = f"upper={len(bl_data['upper'])}, lower={len(bl_data['lower'])}" if bl_data else "not available"
            print(f"BL data: {status}")

        cl = coefficients.get("CL", 0)
        cd = coefficients.get("CD", 0.0001)
        ld = cl / cd if cd > 0 else 0

        print(f"CL={cl:.4f}  CD={cd:.6f}  L/D={ld:.1f}  CP_pts={len(cp_x)}")

        if cd < 0.005 and viscous and reynolds > 100000:
            print(f"Warning: CD={cd:.6f} seems low (expected 0.007-0.012)")
        if ld > 150:
            print(f"Warning: L/D={ld:.0f} unusually high")

        coefficients["mode"] = "viscous" if viscous else "inviscid"
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
@limiter.limit("10/minute")
async def root(request: Request):
    return {"status": "ok", "service": "Airfoil CFD API (BL edition)"}


@app.head("/health")
@app.get("/health")
@limiter.limit("20/minute")
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


@app.post("/upload_airfoil/")
@limiter.limit("5/minute")
async def upload_airfoil(
    request:  Request,
    file:     UploadFile,
    reynolds: float = Form(...),
    alpha:    float = Form(...),
):
    if not (MIN_REYNOLDS <= reynolds <= MAX_REYNOLDS):
        raise HTTPException(status_code=400,
            detail=f"Reynolds must be {MIN_REYNOLDS:,.0f} to {MAX_REYNOLDS:,.0f}")
    if not (MIN_ALPHA <= alpha <= MAX_ALPHA):
        raise HTTPException(status_code=400,
            detail=f"Alpha must be {MIN_ALPHA} to {MAX_ALPHA} degrees")
    if not file.filename.endswith(".dat"):
        raise HTTPException(status_code=400, detail="Only .dat files accepted")

    run_id   = str(uuid.uuid4())[:8]
    work_dir = os.path.join(TMP_DIR, f"run_{run_id}")
    os.makedirs(work_dir, exist_ok=True)

    raw_path = os.path.join(work_dir, "raw.dat")
    fix_path = os.path.join(work_dir, "airfoil_fixed.dat")

    print(f"\n{"="*60}\nNEW REQUEST: {file.filename}\nPlatform: {platform.system()}\n{"="*60}")

    try:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400,
                detail=f"File too large (max {MAX_FILE_SIZE/(1024*1024)}MB)")

        with open(raw_path, "wb") as f:
            f.write(content)

        raw_coords = parse_dat_file(raw_path)
        if len(raw_coords) > MAX_POINTS:
            raise HTTPException(status_code=400, detail=f"Too many points (max {MAX_POINTS})")

        print(f"Parsed: {len(raw_coords)} points")

        with open(fix_path, "w") as f:
            f.write("AIRFOIL\n")
            for x, y in raw_coords:
                f.write(f"  {x:.6f}  {y:.6f}\n")

        async with xfoil_semaphore:
            cp_x, cp_values, coefficients, bl_data = await to_thread.run_sync(
                run_xfoil_sync, fix_path, reynolds, alpha, work_dir
            )

        bl_response = None
        if bl_data is not None:
            bl_response = {
                "upper":              bl_data["upper"],
                "lower":              bl_data["lower"],
                "transition_upper_x": bl_data["transition_upper_x"],
                "transition_lower_x": bl_data["transition_lower_x"],
            }

        return {
            "success":       True,
            "coords_before": raw_coords,
            "coords_after":  raw_coords,
            "num_points":    len(raw_coords),
            "cp_x":          cp_x,
            "cp_values":     cp_values,
            "coefficients":  coefficients,
            "bl_data":       bl_response,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            if os.path.exists(work_dir):
                time.sleep(0.2)
                shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)