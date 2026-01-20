import subprocess
import os
import re
import platform
import time
import uuid
import shutil
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from anyio import to_thread

app = FastAPI(title="Student Airfoil CFD Tool")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    """
    Parse airfoil coordinates from .dat file.
    Handles multiple formats including Selig and Lednicer.
    """
    coords = []
    
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
        
        # Skip header and metadata lines
        data_lines = []
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines
            if not stripped:
                continue
            
            # Skip lines that look like headers
            parts = stripped.split()
            if len(parts) < 2:
                continue
            
            # Try to parse as coordinates
            try:
                x = float(parts[0])
                y = float(parts[1])
                
                # Validate reasonable airfoil coordinates
                if -0.5 <= x <= 1.5 and -1.0 <= y <= 1.0:
                    data_lines.append([x, y])
            except (ValueError, IndexError):
                continue
        
        if len(data_lines) < 10:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient valid coordinates. Found {len(data_lines)} points, need at least 10."
            )
        
        # Detect format and merge sections if needed
        coords = detect_and_merge_sections(data_lines)
        
        return coords
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

def detect_and_merge_sections(data_lines):
    """
    Detect if airfoil data is in two sections (Lednicer format).
    Returns merged coordinates in XFOIL format: TE upper -> LE -> TE lower.
    """
    
    x_coords = [pt[0] for pt in data_lines]
    y_coords = [pt[1] for pt in data_lines]
    
    # Method 1: Look for coordinate jump (classic Lednicer break)
    # This happens when we go from near LE back away from LE
    section_break = None
    for i in range(1, len(data_lines) - 1):
        # Look for a jump where x increases after reaching minimum
        # or where we have a discontinuity in the coordinate sequence
        x_prev, x_curr = x_coords[i-1], x_coords[i]
        
        # Classic Lednicer: after reaching LE (x≈0), x jumps to small positive value
        if x_prev < 0.01 and x_curr > x_prev + 0.005 and x_curr < 0.1:
            section_break = i
            print(f"DEBUG: Found section break at index {i} (x jump from {x_prev:.5f} to {x_curr:.5f})")
            break
    
    # Method 2: Check if we visit LE (x≈0) twice - another Lednicer indicator
    if section_break is None:
        le_indices = [i for i, x in enumerate(x_coords) if x < 0.01]
        if len(le_indices) > 1:
            # Find the gap between LE visits
            for j in range(len(le_indices) - 1):
                if le_indices[j+1] - le_indices[j] > 1:
                    section_break = le_indices[j] + 1
                    print(f"DEBUG: Found section break between LE visits at index {section_break}")
                    break
    
    if section_break is not None:
        # Two-section format (Lednicer)
        upper = data_lines[:section_break]
        lower = data_lines[section_break:]
        
        print(f"DEBUG: Detected Lednicer format with {len(upper)} upper, {len(lower)} lower points")
        print(f"DEBUG: Upper section: x from {upper[0][0]:.4f} to {upper[-1][0]:.4f}")
        print(f"DEBUG: Lower section: x from {lower[0][0]:.4f} to {lower[-1][0]:.4f}")
        
        # XFOIL expects: TE (x=1) -> LE (x=0) on upper, then LE (x=0) -> TE (x=1) on lower
        # Upper surface: should go from high x to low x (TE to LE)
        if upper[0][0] < upper[-1][0]:
            upper = list(reversed(upper))
            print(f"DEBUG: Reversed upper surface")
        
        # Lower surface: should go from low x to high x (LE to TE)  
        if lower[0][0] > lower[-1][0]:
            lower = list(reversed(lower))
            print(f"DEBUG: Reversed lower surface")
        
        # Check if we need to remove duplicate leading edge point
        if len(upper) > 0 and len(lower) > 0:
            if abs(upper[-1][0] - lower[0][0]) < 0.001 and abs(upper[-1][1] - lower[0][1]) < 0.001:
                print(f"DEBUG: Removing duplicate LE point")
                merged = upper + lower[1:]
            else:
                merged = upper + lower
        else:
            merged = upper + lower
            
        print(f"DEBUG: Final merged: {len(merged)} points, x from {merged[0][0]:.4f} to {merged[-1][0]:.4f}")
    else:
        # Single continuous section - check if it's already in correct order
        print(f"DEBUG: Single section format with {len(data_lines)} points")
        
        # Check if it starts near TE (x≈1)
        if data_lines[0][0] < 0.5 and data_lines[-1][0] > 0.5:
            # Starts at LE, ends at TE - need to reverse
            merged = list(reversed(data_lines))
            print(f"DEBUG: Reversed single section to start at TE")
        else:
            merged = data_lines
    
    # Remove duplicate trailing edge if exists
    if len(merged) > 1 and abs(merged[0][0] - merged[-1][0]) < 0.001 and abs(merged[0][1] - merged[-1][1]) < 0.001:
        merged = merged[:-1]
        print(f"DEBUG: Removed duplicate TE point")
    
    return merged

def extract_aerodynamic_coefficients(stdout: str):
    """Extract CL, CD, and other coefficients from XFOIL output."""
    coefficients = {}
    patterns = {
        'CL': r'CL\s*=\s*([-+]?\d*\.?\d+)',
        'CD': r'CD\s*=\s*([-+]?\d*\.?\d+)',
        'CDp': r'CDp\s*=\s*([-+]?\d*\.?\d+)',
        'CM': r'CM\s*=\s*([-+]?\d*\.?\d+)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, stdout)
        if match:
            coefficients[key] = float(match.group(1))
    return coefficients

def run_xfoil_sync(coords_file: str, reynolds: float, alpha: float, work_dir: str, retry_simple: bool = False):
    """
    Run XFOIL simulation synchronously (will be called in a thread).
    Uses isolated work directory to prevent race conditions.
    retry_simple: if True, use simpler XFOIL commands for problematic airfoils
    """
    # Simple filenames - XFOIL runs in work_dir
    coords_filename = "airfoil.dat"
    cp_filename = "cp_output.txt"
    
    # Copy coords file to work directory
    work_coords = os.path.join(work_dir, coords_filename)
    shutil.copy(coords_file, work_coords)
    
    cp_out_path = os.path.join(work_dir, cp_filename)
    
    # Choose command set based on retry mode
    if retry_simple:
        # Simplified commands for problematic airfoils
        print("DEBUG: Using simplified XFOIL mode (no geometry refinement)")
        if IS_WINDOWS:
            commands = [
                f"LOAD {coords_filename}",
                "OPER",
                f"VISC {reynolds}",
                "ITER 80",
                f"ALFA {alpha}",
                f"CPWR {cp_filename}",
                "",
                "QUIT"
            ]
        else:
            commands = [
                f"LOAD {coords_filename}",
                "OPER",
                f"VISC {reynolds}",
                "ITER 100",
                f"ALFA {alpha}",
                f"CPWR {cp_filename}",
                "",
                "QUIT"
            ]
    else:
        # Standard commands - simpler geometry handling
        if IS_WINDOWS:
            commands = [
                f"LOAD {coords_filename}",
                "PANE",
                "OPER",
                f"VISC {reynolds}",
                "ITER 100",
                f"ALFA {alpha}",
                f"CPWR {cp_filename}",
                "",
                "QUIT"
            ]
        else:
            commands = [
                f"LOAD {coords_filename}",
                "PANE",
                "OPER",
                f"VISC {reynolds}",
                "ITER 150",
                f"ALFA {alpha}",
                f"CPWR {cp_filename}",
                "",
                "QUIT"
            ]

    try:
        input_str = "\n".join(commands) + "\n"
        
        # Run XFOIL in isolated work directory
        if not IS_WINDOWS:
            # Use Xvfb to provide virtual display
            xvfb_cmd = ['xvfb-run', '-a', '--server-args=-screen 0 1024x768x24', XFOIL_EXE]
            proc = subprocess.Popen(
                xvfb_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=work_dir
            )
        else:
            proc = subprocess.Popen(
                [XFOIL_EXE],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=work_dir
            )
        
        stdout, stderr = proc.communicate(input=input_str, timeout=45)
        
        # Give filesystem time to write
        time.sleep(0.3)
        
        # Debug logging
        print(f"\n=== XFOIL RUN DEBUG ===")
        print(f"Work Dir: {work_dir}")
        print(f"Reynolds: {reynolds}, Alpha: {alpha}")
        print(f"Return Code: {proc.returncode}")
        
        # Check for convergence issues
        if "VISCAL:  Convergence failed" in stdout:
            print(f"CONVERGENCE FAILURE")
            raise Exception(
                "XFOIL convergence failed. Try different parameters."
            )
        
        # Check for other XFOIL errors
        if "SIGFPE" in stderr or "Floating-point exception" in stderr:
            print(f"FLOATING POINT ERROR:")
            print(stderr[:500])
            raise Exception("XFOIL encountered a numerical error. Try different parameters or check airfoil geometry.")
        
        # Verify output file exists
        if not os.path.exists(cp_out_path):
            print(f"\n=== OUTPUT FILE NOT FOUND ===")
            print(f"XFOIL STDOUT (last 1500 chars):")
            print(stdout[-1500:])
            print(f"\nXFOIL STDERR:")
            print(stderr[:500] if stderr else "(empty)")
            raise Exception(
                "XFOIL did not generate pressure distribution. "
                "Check airfoil geometry or try different parameters."
            )

        # Extract coefficients
        coefficients = extract_aerodynamic_coefficients(stdout)
        
        # Parse Cp file
        cp_x, cp_values = [], []
        with open(cp_out_path, "r") as f:
            for line in f:
                clean = line.strip()
                if not clean or any(c.isalpha() for c in clean) or clean.startswith("#"):
                    continue
                parts = clean.split()
                if len(parts) >= 2:
                    try:
                        cp_x.append(float(parts[0]))
                        cp_values.append(float(parts[1]))
                    except ValueError:
                        continue
        
        if not cp_x:
            raise Exception("No pressure data extracted from XFOIL output")
        
        print(f"✅ SUCCESS: Got {len(cp_x)} pressure points")
            
        return cp_x, cp_values, coefficients

    except subprocess.TimeoutExpired:
        if 'proc' in locals():
            proc.kill()
        raise Exception("XFOIL timeout (>45s). This airfoil may have convergence issues. Try: lower Reynolds number, different angle of attack, or a simpler airfoil geometry.")
    except Exception as e:
        raise e

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok", 
        "service": "Airfoil CFD API",
        "xfoil_path": XFOIL_EXE
    }

@app.get("/health")
async def health():
    """Detailed health check"""
    xfoil_exists = os.path.exists(XFOIL_EXE)
    if not xfoil_exists and not IS_WINDOWS:
        xfoil_exists = os.system(f"which {XFOIL_EXE} >/dev/null 2>&1") == 0
    
    xfoil_runnable = False
    xfoil_version = "unknown"
    if xfoil_exists:
        try:
            result = subprocess.run(
                [XFOIL_EXE], 
                input="QUIT\n", 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            xfoil_runnable = result.returncode == 0 or "XFOIL" in result.stdout
            if "XFOIL" in result.stdout:
                for line in result.stdout.split('\n'):
                    if "XFOIL" in line or "Version" in line:
                        xfoil_version = line.strip()
                        break
        except Exception as e:
            xfoil_version = f"Error: {str(e)}"
    
    # Xvfb not needed - we compiled without X11
    xvfb_available = "Not needed (compiled without X11)"
    
    return {
        "status": "healthy" if xfoil_exists and xfoil_runnable else "degraded",
        "xfoil_path": XFOIL_EXE,
        "xfoil_exists": xfoil_exists,
        "xfoil_runnable": xfoil_runnable,
        "xfoil_version": xfoil_version,
        "xvfb_available": xvfb_available,
        "tmp_dir": TMP_DIR,
        "platform": platform.system(),
        "tmp_dir_writable": os.access(TMP_DIR, os.W_OK)
    }

@app.post("/upload_airfoil/")
async def upload_airfoil(
    file: UploadFile, 
    reynolds: float = Form(...), 
    alpha: float = Form(...)
):
    """
    Upload and analyze an airfoil.
    Accepts .dat files in Selig or Lednicer format.
    Uses isolated work directories and async execution.
    """
    run_id = str(uuid.uuid4())[:8]
    
    # Create isolated work directory for this request
    work_dir = os.path.join(TMP_DIR, f"run_{run_id}")
    os.makedirs(work_dir, exist_ok=True)
    
    raw_path = os.path.join(work_dir, f"raw.dat")
    fix_path = os.path.join(work_dir, f"airfoil_fixed.dat")
    
    print(f"\n{'='*60}")
    print(f"NEW REQUEST: {file.filename}")
    print(f"Work Dir: {work_dir}")
    print(f"Reynolds: {reynolds}, Alpha: {alpha}")
    print(f"{'='*60}\n")
    
    try:
        # Save uploaded file
        content = await file.read()
        with open(raw_path, "wb") as f:
            f.write(content)
        
        # Parse coordinates
        raw_coords = parse_dat_file(raw_path)
        print(f"Parsed: {len(raw_coords)} points")
        
        # Write XFOIL-compatible file (minimal reordering, trust PANE)
        with open(fix_path, "w") as f:
            f.write("AIRFOIL\n")
            for x, y in raw_coords:
                f.write(f"  {x:.6f}  {y:.6f}\n")
        
        # Run XFOIL in a separate thread to avoid blocking
        try:
            cp_x, cp_values, coefficients = await to_thread.run_sync(
                run_xfoil_sync, fix_path, reynolds, alpha, work_dir, False
            )
        except Exception as e:
            # If first attempt fails with timeout, try simplified mode ONCE
            if "timeout" in str(e).lower():
                print("⚠️ First attempt timed out, retrying with simplified XFOIL commands (final attempt)...")
                try:
                    cp_x, cp_values, coefficients = await to_thread.run_sync(
                        run_xfoil_sync, fix_path, reynolds, alpha, work_dir, True
                    )
                except Exception as retry_error:
                    # If retry also fails, give up with helpful message
                    print(f"❌ Retry also failed: {str(retry_error)}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"XFOIL failed to converge after 2 attempts. This airfoil may be incompatible with XFOIL at Re={reynolds:,.0f} and α={alpha}°. Try: (1) Lower Reynolds (100k-300k), (2) Different angle (0-3°), or (3) Different airfoil."
                    )
            else:
                raise
        
        print(f"✅ Analysis complete")
        
        return {
            "success": True,
            "message": "Analysis completed successfully",
            "coords_before": raw_coords,
            "coords_after": raw_coords,  # Trusting PANE, not modifying
            "num_points": len(raw_coords),
            "cp_x": cp_x,
            "cp_values": cp_values,
            "coefficients": coefficients
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup work directory (with retry for Windows)
        try:
            if os.path.exists(work_dir):
                # Give Windows time to release file handles
                time.sleep(0.2)
                shutil.rmtree(work_dir, ignore_errors=True)
                print(f"Cleaned up: {work_dir}")
        except Exception as e:
            print(f"Warning: Could not cleanup {work_dir}: {e}")
            # Not critical - OS will clean temp files eventually

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)