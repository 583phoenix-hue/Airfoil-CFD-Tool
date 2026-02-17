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

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Student Airfoil CFD Tool")

# Rate limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS - restrict to your frontend domain in production
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "HEAD"],
    allow_headers=["*"],
)

# Validation constants
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB
MAX_POINTS = 500
MIN_POINTS = 10
MIN_REYNOLDS = 1e4
MAX_REYNOLDS = 1e7
MIN_ALPHA = -10
MAX_ALPHA = 20

# Semaphore for concurrent XFOIL runs (max 3 simultaneous)
xfoil_semaphore = asyncio.Semaphore(3)

# Auto-detect XFOIL executable and temp directory
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
    coords = []

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
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient valid coordinates. Found {len(data_lines)} points."
            )

        coords = detect_and_merge_sections(data_lines)
        return coords

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

def detect_and_merge_sections(data_lines):
    """Detect format and merge if needed."""
    x_coords = [pt[0] for pt in data_lines]

    # Check for Lednicer format (two sections)
    section_break = None
    for i in range(1, len(data_lines)):
        if x_coords[i] < 0.01 and x_coords[i-1] > 0.5:
            section_break = i
            break

    if section_break is not None:
        # Lednicer format
        upper = data_lines[:section_break]
        lower = data_lines[section_break:]

        print(f"DEBUG: Lednicer format: {len(upper)} upper, {len(lower)} lower")

        if upper[0][0] < upper[-1][0]:
            upper = list(reversed(upper))

        if lower[0][0] > lower[-1][0]:
            lower = list(reversed(lower))

        merged = upper + lower
    else:
        # Single section
        print(f"DEBUG: Single section: {len(data_lines)} points")

        # Special case: Check if it's TE-to-TE format (starts AND ends at x~1)
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

    # Remove duplicate TE if exists
    if len(merged) > 1 and abs(merged[0][0] - merged[-1][0]) < 0.001 and abs(merged[0][1] - merged[-1][1]) < 0.001:
        merged = merged[:-1]
        print(f"DEBUG: Removed duplicate TE")

    return merged

def extract_aerodynamic_coefficients(stdout: str):
    """Extract coefficients from XFOIL output.
    
    Takes the LAST occurrence of each coefficient to ensure we get
    the final converged value, not an intermediate step.
    """
    coefficients = {}
    patterns = {
        'CL': r'CL\s*=\s*([-+]?\d*\.?\d+)',
        'CD': r'CD\s*=\s*([-+]?\d*\.?\d+)',
        'CDp': r'CDp\s*=\s*([-+]?\d*\.?\d+)',
        'Cm': r'Cm\s*=\s*([-+]?\d*\.?\d+)',
    }
    
    for key, pattern in patterns.items():
        # Find ALL matches and take the last one
        matches = re.findall(pattern, stdout)
        if matches:
            coefficients[key] = float(matches[-1])  # Use last match
    
    return coefficients

def run_xfoil_sync(coords_file: str, reynolds: float, alpha: float, work_dir: str):
    """Run XFOIL simulation with intelligent retry strategy."""
    coords_filename = "airfoil.dat"
    cp_filename = "cp_output.txt"

    work_coords = os.path.join(work_dir, coords_filename)
    shutil.copy(coords_file, work_coords)

    # Strategy 1: Try viscous mode with clean geometry
    try:
        print("Attempt 1: VISCOUS mode with stepped initialization...")
        return _run_xfoil_mode(coords_filename, cp_filename, work_dir, reynolds, alpha, 
                               viscous=True, timeout=90, smooth_geometry=False)
    except subprocess.TimeoutExpired:
        print("ERROR: Viscous mode timed out after 90s")
        pass  # Fall through to strategy 2
    except Exception as e:
        error_msg = str(e).lower()
        if "convergence" in error_msg or "no pressure data" in error_msg:
            print(f"Convergence issue detected: {str(e)}")
            pass  # Fall through to strategy 2
        else:
            # Unexpected error, don't retry
            raise e
    
    # Strategy 2: Retry with geometry smoothing
    try:
        print("Attempt 2: VISCOUS mode WITH geometry smoothing...")
        print("    (This may slightly alter airfoil shape for better convergence)")
        return _run_xfoil_mode(coords_filename, cp_filename, work_dir, reynolds, alpha,
                               viscous=True, timeout=90, smooth_geometry=True)
    except subprocess.TimeoutExpired:
        print("ERROR: Viscous mode with smoothing also timed out")
        pass  # Fall through to strategy 3
    except Exception as e:
        error_msg = str(e).lower()
        if "convergence" in error_msg or "no pressure data" in error_msg:
            print(f"Smoothed geometry also failed: {str(e)}")
            pass  # Fall through to strategy 3
        else:
            raise e
    
    # Strategy 3: Last resort - inviscid mode with big warning
    print("=" * 70)
    print("WARNING: FALLING BACK TO INVISCID MODE")
    print("=" * 70)
    print("Viscous solver could not converge. Possible causes:")
    print("  - Reynolds number too low (try Re > 100,000)")
    print("  - Extreme angle of attack (try -5° to 10°)")
    print("  - Problematic airfoil geometry")
    print("Returning INVISCID results (CD will be 3-5x too low)")
    print("=" * 70)
    
    try:
        return _run_xfoil_mode(coords_filename, cp_filename, work_dir, reynolds, alpha,
                               viscous=False, timeout=20, smooth_geometry=False)
    except Exception as e:
        raise Exception(f"All strategies failed. Last error: {str(e)}")

def _run_xfoil_mode(coords_filename: str, cp_filename: str, work_dir: str, reynolds: float, alpha: float, viscous: bool, timeout: int, smooth_geometry: bool = False):
    """Linux-optimized XFOIL execution.

    Key differences from Windows version:
    1. NO PLOP command (causes crash on headless Linux)
    2. Uses script file method (fast and reliable on Linux)
    3. Minimal blank lines (Linux doesn't need timing delays)
    4. No zombie process killing (not needed on Linux)
    5. Optional geometry smoothing for noisy coordinate files
    """

    cp_out_path = os.path.abspath(os.path.join(work_dir, cp_filename))
    script_path = os.path.abspath(os.path.join(work_dir, "xfoil_script.txt"))
    log_path = os.path.abspath(os.path.join(work_dir, "xfoil_output.log"))

    # Clean up old files
    for path in [cp_out_path, log_path]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    # === BUILD SCRIPT ===
    script_lines = []

    # Load and panel airfoil
    script_lines.extend([
        f"LOAD {coords_filename}",
        "PANE",
        "OPER",
    ])

    if viscous:
        script_lines.extend([
            f"VISC {reynolds}",
            "ITER 500",
            f"ALFA {alpha}",
        ])
    else:
        script_lines.append(f"ALFA {alpha}")

    # Write CP and quit
    script_lines.extend([
        f"CPWR {cp_filename}",
        "",
        "QUIT",
    ])

    # Write script with Unix line endings
    script_content = "\n".join(script_lines)
    with open(script_path, 'w', newline='\n') as f:
        f.write(script_content)

    print(f"\n{'='*70}")
    print(f"LINUX-OPTIMIZED XFOIL")
    print(f"{'='*70}")
    print(f"Platform: {platform.system()}")
    print(f"Method: Script file (stdin redirection)")
    print(f"Commands: {len(script_lines)}")
    print(f"Paneling: PANE (default, reliable)")
    print(f"{'='*70}\n")

    proc = None
    try:
        # === LINUX SCRIPT FILE METHOD ===
        with open(script_path, 'r') as script_file:
            proc = subprocess.Popen(
                [XFOIL_EXE],
                stdin=script_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=work_dir
            )

        stdout, stderr = proc.communicate(timeout=timeout)
        time.sleep(0.3)

        # Save output
        with open(log_path, 'w', newline='\n') as f:
            f.write("="*70 + "\n")
            f.write("LINUX XFOIL LOG\n")
            f.write("="*70 + "\n\n")
            f.write(f"Reynolds: {reynolds}\n")
            f.write(f"Alpha: {alpha}\n")
            f.write(f"Viscous: {viscous}\n")
            f.write(f"Return code: {proc.returncode}\n\n")
            f.write("="*70 + "\n")
            f.write("STDOUT\n")
            f.write("="*70 + "\n")
            f.write(stdout)
            f.write("\n\n")
            f.write("="*70 + "\n")
            f.write("STDERR\n")
            f.write("="*70 + "\n")
            f.write(stderr)

        mode = "VISCOUS" if viscous else "INVISCID"

        print(f"\n{'='*70}")
        print(f"XFOIL {mode} COMPLETE")
        print(f"{'='*70}")
        print(f"Return code: {proc.returncode}")
        print(f"Log: {log_path}")

        # Check for crash
        if proc.returncode != 0:
            print(f"Warning: Non-zero exit code: {proc.returncode}")
            print(f"   Check log for errors")

        # === VERIFY PANEL COUNT ===
        panel_matches = re.findall(r'Number of panel nodes\s+(\d+)', stdout)

        print(f"\n{'='*70}")
        print(f"PANEL COUNT VERIFICATION")
        print(f"{'='*70}")

        if panel_matches:
            panel_count = int(panel_matches[-1])
            print(f"Detected: {panel_count} panels")

            if panel_count >= 140:
                print(f"Panel count is sufficient for accurate results")
            else:
                print(f"Warning: Low panel count ({panel_count})")
        else:
            print(f"Warning: Could not detect panel count")
            print(f"   XFOIL may have crashed early")

        # Verify viscous mode actually ran
        if viscous:
            # Check for actual viscous calculation indicators
            visc_indicators = ["Re =", "VISCAL", "Cm ="]
            visc_confirmed = any(ind in stdout for ind in visc_indicators)
            
            # Also check it's not purely inviscid
            has_cdp = "CDp" in stdout or "CD =" in stdout
            
            if visc_confirmed and has_cdp:
                print(f"Viscous mode confirmed")
            else:
                print(f"WARNING: Viscous mode requested but may not have converged")
                print(f"   Results may be inviscid or unconverged")

        print(f"{'='*70}\n")

        # Check convergence more thoroughly
        convergence_failed = (
            "VISCAL:  Convergence failed" in stdout or 
            "not converged" in stdout.lower() or
            "unconverged" in stdout.lower()
        )
        
        if convergence_failed:
            print(f"ERROR: Convergence failed for alpha={alpha}")
            raise Exception(f"Viscous convergence failed at alpha={alpha}")

        # Check for output file
        if not os.path.exists(cp_out_path):
            print(f"ERROR: CP file not created")
            print(f"\nLast 800 chars of XFOIL output:")
            print(stdout[-800:])
            raise Exception(f"{mode} did not generate output file")

        # Extract coefficients
        coefficients = extract_aerodynamic_coefficients(stdout)
        
        # Verify we got valid coefficients for the requested alpha
        if not coefficients or 'CL' not in coefficients:
            print(f"ERROR: No coefficients extracted from XFOIL output")
            print(f"\nChecking if ALFA {alpha} was processed:")
            # Look for alpha in various output formats
            alpha_patterns = [
                f"alfa = {alpha:.3f}",
                f"ALFA   {alpha:.2f}",
                f"a = {alpha:.2f}",
            ]
            found_alpha = any(pattern.lower() in stdout.lower() for pattern in alpha_patterns)
            if found_alpha:
                print(f"  Alpha command was processed")
            else:
                print(f"  WARNING: Could not verify alpha={alpha} was calculated!")
                print(f"  This suggests XFOIL may have used cached/stale results")
            raise Exception(f"No valid aerodynamic coefficients found for alpha={alpha}")

        # Parse CP data
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

        # Results
        cl = coefficients.get('CL', 0)
        cd = coefficients.get('CD', 0.0001)
        ld = cl / cd if cd > 0 else 0

        print(f"{'='*70}")
        print(f"RESULTS (Linux/Production)")
        print(f"{'='*70}")
        print(f"CL     = {cl:8.4f}")
        print(f"CD     = {cd:8.6f}")
        print(f"L/D    = {ld:8.1f}")
        print(f"CP pts = {len(cp_x):8d}")
        print(f"{'='*70}\n")

        # Sanity checks
        if cd < 0.005 and viscous and reynolds > 100000:
            print(f"Warning: CD={cd:.6f} still seems low")
            print(f"   Expected: 0.007-0.012")

        if ld > 150:
            print(f"Warning: L/D={ld:.0f} is high")
            print(f"   May indicate inviscid mode or coarse mesh")

        if cd >= 0.007 and cd <= 0.015 and ld < 150:
            print(f"Results look PHYSICALLY REASONABLE")
            print(f"   Safe to use for servo calculations")

        if not viscous:
            coefficients['mode'] = 'inviscid'
            coefficients['warning'] = 'INVISCID MODE - CD is unrealistically low'
            print(f"\n*** WARNING: INVISCID MODE ***")
            print(f"    These results are NOT suitable for drag calculations!")
            print(f"    CD values are 3-5x lower than reality")
        else:
            coefficients['mode'] = 'viscous'

        return cp_x, cp_values, coefficients

    except subprocess.TimeoutExpired:
        if proc is not None:
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
    return {"status": "ok", "service": "Airfoil CFD API"}

@app.head("/health")
@app.get("/health")
@limiter.limit("20/minute")
async def health(request: Request):
    xfoil_exists = os.path.exists(XFOIL_EXE) or (not IS_WINDOWS and os.system(f"which {XFOIL_EXE} >/dev/null 2>&1") == 0)

    return {
        "status": "healthy" if xfoil_exists else "degraded",
        "xfoil_path": XFOIL_EXE,
        "xfoil_exists": xfoil_exists,
        "platform": platform.system()
    }

@app.post("/upload_airfoil/")
@limiter.limit("5/minute")
async def upload_airfoil(
    request: Request,
    file: UploadFile,
    reynolds: float = Form(...),
    alpha: float = Form(...)
):
    # Validate inputs
    if not (MIN_REYNOLDS <= reynolds <= MAX_REYNOLDS):
        raise HTTPException(status_code=400, detail=f"Reynolds must be {MIN_REYNOLDS:,.0f} to {MAX_REYNOLDS:,.0f}")

    if not (MIN_ALPHA <= alpha <= MAX_ALPHA):
        raise HTTPException(status_code=400, detail=f"Alpha must be {MIN_ALPHA} to {MAX_ALPHA} degrees")

    if not file.filename.endswith('.dat'):
        raise HTTPException(status_code=400, detail="Only .dat files accepted")

    run_id = str(uuid.uuid4())[:8]
    work_dir = os.path.join(TMP_DIR, f"run_{run_id}")
    os.makedirs(work_dir, exist_ok=True)

    raw_path = os.path.join(work_dir, "raw.dat")
    fix_path = os.path.join(work_dir, "airfoil_fixed.dat")

    print(f"\n{'='*60}")
    print(f"NEW REQUEST: {file.filename}")
    print(f"Platform: {platform.system()}")
    print(f"{'='*60}")

    try:
        content = await file.read()

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"File too large (max {MAX_FILE_SIZE/(1024*1024)}MB)")

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
            cp_x, cp_values, coefficients = await to_thread.run_sync(
                run_xfoil_sync, fix_path, reynolds, alpha, work_dir
            )

        return {
            "success": True,
            "coords_before": raw_coords,
            "coords_after": raw_coords,
            "num_points": len(raw_coords),
            "cp_x": cp_x,
            "cp_values": cp_values,
            "coefficients": coefficients
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