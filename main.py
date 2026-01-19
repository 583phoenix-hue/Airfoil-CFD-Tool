import subprocess
import os
import re
import platform
import time
import uuid
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
    Handles multiple formats:
    - Selig format (continuous list from TE->upper->LE->lower->TE)
    - Lednicer format (two separate sections: upper then lower)
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
            
            # Skip lines that look like headers (all text or single numbers)
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
        
        # Detect format: Check if coordinates are split into two sections
        coords = detect_and_merge_sections(data_lines)
        
        return coords
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

def detect_and_merge_sections(data_lines):
    """
    Detect if airfoil data is in two sections (Lednicer format) or continuous (Selig).
    Returns merged coordinates in Selig format: TE -> upper -> LE -> lower -> TE
    """
    
    x_coords = [pt[0] for pt in data_lines]
    y_coords = [pt[1] for pt in data_lines]
    
    # Find where x goes back to 0 (indicating start of second section)
    # Clark Y format: upper surface (1→0), then lower surface (0→1)
    section_break = None
    
    # Look for the point where x returns to near 0 after being at 1
    for i in range(1, len(data_lines)):
        # If we find x≈0 after we've been at higher x values
        if x_coords[i] < 0.01 and x_coords[i-1] > 0.5:
            section_break = i
            break
    
    if section_break is not None:
        # Two-section format (Lednicer)
        upper = data_lines[:section_break]
        lower = data_lines[section_break:]
        
        print(f"DEBUG: Detected Lednicer format")
        print(f"  Upper section: {len(upper)} points, x from {upper[0][0]:.3f} to {upper[-1][0]:.3f}")
        print(f"  Lower section: {len(lower)} points, x from {lower[0][0]:.3f} to {lower[-1][0]:.3f}")
        
        # Upper surface should go from TE to LE (x: 1→0)
        if upper[0][0] < upper[-1][0]:
            print(f"  Reversing upper surface")
            upper = list(reversed(upper))
        
        # Lower surface should go from LE to TE (x: 0→1)
        if lower[0][0] > lower[-1][0]:
            print(f"  Reversing lower surface")
            lower = list(reversed(lower))
        
        # XFOIL wants: start at TE upper, go to LE, then LE to TE lower
        # So: upper (TE→LE) + lower (LE→TE)
        merged = upper + lower
        
    else:
        # Single continuous section (Selig format)
        print(f"DEBUG: Detected Selig format (continuous)")
        merged = data_lines
    
    # Remove duplicate trailing edge point if it exists
    if len(merged) > 1 and abs(merged[0][0] - merged[-1][0]) < 0.001 and abs(merged[0][1] - merged[-1][1]) < 0.001:
        merged = merged[:-1]
    
    print(f"DEBUG: Final merged: {len(merged)} points, x from {merged[0][0]:.3f} to {merged[-1][0]:.3f}")
    
    return merged

def reorder_to_xfoil_standard(coords):
    """
    Ensure coordinates are in XFOIL standard format.
    XFOIL expects: Start from TE (upper), go to LE, then back to TE (lower).
    
    Format should be: TE_upper -> ... -> LE -> ... -> TE_lower
    """
    if len(coords) < 3:
        return coords
    
    x_vals = [c[0] for c in coords]
    y_vals = [c[1] for c in coords]
    
    # Find leading edge (minimum x)
    le_idx = x_vals.index(min(x_vals))
    
    print(f"DEBUG: LE at index {le_idx}, x={coords[le_idx][0]:.4f}, y={coords[le_idx][1]:.4f}")
    
    # Check current order
    # If starting point is at TE (x close to 1), we're probably good
    if x_vals[0] > 0.9:
        print(f"DEBUG: Already starts at TE (x={x_vals[0]:.4f}), keeping order")
        return coords
    
    # If starting at LE (x close to 0), need to reorder
    if x_vals[0] < 0.1:
        print(f"DEBUG: Starts at LE (x={x_vals[0]:.4f}), reordering...")
        
        # Find where upper surface ends (at TE, x≈1, y>0)
        # Split at LE, then recombine starting from TE upper
        upper = coords[:le_idx+1]  # From start to LE
        lower = coords[le_idx+1:]   # From LE to end
        
        # Reverse upper so it goes TE→LE instead of LE→TE
        upper_reversed = list(reversed(upper))
        
        reordered = upper_reversed + lower
        print(f"DEBUG: Reordered to start from TE")
        return reordered
    
    # Otherwise, assume it's already in correct format
    print(f"DEBUG: Format looks correct, keeping as-is")
    return coords

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

def run_xfoil(coords_file: str, reynolds: float, alpha: float):
    """Run XFOIL simulation and return results."""
    run_id = str(uuid.uuid4())[:8]
    
    # Use just filenames (no paths) to avoid Windows space issues
    coords_filename = f"airfoil_{run_id}.dat"
    cp_filename = f"cp_{run_id}.txt"
    
    coords_path = os.path.join(TMP_DIR, coords_filename)
    cp_out_path = os.path.join(TMP_DIR, cp_filename)
    
    # Copy input file to working directory with simple name
    import shutil
    shutil.copy(coords_file, coords_path)
    
    if os.path.exists(cp_out_path):
        os.remove(cp_out_path)

    # OS-specific XFOIL commands - use ONLY filenames, not full paths
    if IS_WINDOWS:
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
    else:
        # Headless Linux (Render)
        commands = [
            "PLOP", "G", "",  # Disable graphics
            f"LOAD {coords_filename}",
            "PANE",
            "OPER",
            f"VISC {reynolds}",
            "ITER 200",
            f"ALFA {alpha}",
            f"CPWR {cp_filename}",
            "",  # Confirm write
            "QUIT"
        ]

    try:
        input_str = "\n".join(commands) + "\n"
        proc = subprocess.Popen(
            [XFOIL_EXE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=TMP_DIR
        )
        
        stdout, stderr = proc.communicate(input=input_str, timeout=60)
        
        # Give filesystem time to write
        time.sleep(0.5)
        
        # DETAILED LOGGING FOR RENDER
        print(f"\n=== XFOIL RUN DEBUG ===")
        print(f"XFOIL Path: {XFOIL_EXE}")
        print(f"Working Dir: {TMP_DIR}")
        print(f"Coords File: {coords_filename}")
        print(f"Output File: {cp_filename}")
        print(f"Reynolds: {reynolds}, Alpha: {alpha}")
        print(f"Return Code: {proc.returncode}")
        
        # Check for convergence issues
        if "VISCAL:  Convergence failed" in stdout:
            print(f"CONVERGENCE FAILURE - Last 1000 chars of output:")
            print(stdout[-1000:])
            raise Exception(
                "XFOIL convergence failed. Try: (1) different angle of attack, "
                "(2) different Reynolds number, or (3) increase iterations."
            )
        
        # Verify output file exists
        if not os.path.exists(cp_out_path):
            print(f"\n=== OUTPUT FILE NOT FOUND ===")
            print(f"Looking for: {cp_out_path}")
            print(f"Files in {TMP_DIR}:")
            try:
                print(os.listdir(TMP_DIR))
            except:
                print("Could not list directory")
            
            print(f"\n=== XFOIL STDOUT (last 2000 chars) ===")
            print(stdout[-2000:])
            
            print(f"\n=== XFOIL STDERR ===")
            print(stderr if stderr else "(empty)")
            
            print(f"\n=== COORDS FILE CONTENT ===")
            try:
                with open(coords_file, 'r') as f:
                    print(f.read()[:500])
            except:
                print("Could not read coords file")
            
            raise Exception(
                "XFOIL did not generate pressure distribution. "
                "Check Render logs for detailed XFOIL output."
            )

        # Extract coefficients
        coefficients = extract_aerodynamic_coefficients(stdout)
        
        # Parse Cp file
        cp_x, cp_values = [], []
        with open(cp_out_path, "r") as f:
            for line in f:
                clean = line.strip()
                # Skip headers and empty lines
                if not clean or any(c.isalpha() for c in clean) or clean.startswith("#"):
                    continue
                parts = clean.split()
                if len(parts) >= 2:
                    try:
                        cp_x.append(float(parts[0]))
                        cp_values.append(float(parts[1]))
                    except ValueError:
                        continue
        
        # Cleanup
        if os.path.exists(cp_out_path):
            os.remove(cp_out_path)
        
        if not cp_x:
            raise Exception("No pressure data extracted from XFOIL output")
            
        return cp_x, cp_values, coefficients

    except subprocess.TimeoutExpired:
        if 'proc' in locals():
            proc.kill()
        raise Exception("XFOIL timeout (>60s). Try simpler parameters.")
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
    # Check if XFOIL exists
    xfoil_exists = os.path.exists(XFOIL_EXE)
    if not xfoil_exists and not IS_WINDOWS:
        xfoil_exists = os.system(f"which {XFOIL_EXE} >/dev/null 2>&1") == 0
    
    # Try to run XFOIL to verify it works
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
                # Try to extract version
                for line in result.stdout.split('\n'):
                    if "XFOIL" in line or "Version" in line:
                        xfoil_version = line.strip()
                        break
        except Exception as e:
            xfoil_version = f"Error: {str(e)}"
    
    return {
        "status": "healthy" if xfoil_exists and xfoil_runnable else "degraded",
        "xfoil_path": XFOIL_EXE,
        "xfoil_exists": xfoil_exists,
        "xfoil_runnable": xfoil_runnable,
        "xfoil_version": xfoil_version,
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
    """
    run_id = str(uuid.uuid4())[:8]
    raw_path = os.path.join(TMP_DIR, f"raw_{run_id}.dat")
    fix_path = os.path.join(TMP_DIR, f"fix_{run_id}.dat")
    
    try:
        # Save uploaded file
        content = await file.read()
        with open(raw_path, "wb") as f:
            f.write(content)
        
        # Parse and fix coordinates
        raw_coords = parse_dat_file(raw_path)
        print(f"\n=== PARSING {file.filename} ===")
        print(f"Raw coords: {len(raw_coords)} points")
        
        fixed_coords = reorder_to_xfoil_standard(raw_coords)
        print(f"Fixed coords: {len(fixed_coords)} points")
        print(f"First point: x={fixed_coords[0][0]:.4f}, y={fixed_coords[0][1]:.4f}")
        print(f"Last point: x={fixed_coords[-1][0]:.4f}, y={fixed_coords[-1][1]:.4f}")
        
        # Write XFOIL-compatible file
        with open(fix_path, "w") as f:
            f.write("AIRFOIL\n")
            for x, y in fixed_coords:
                f.write(f"  {x:.6f}  {y:.6f}\n")
        
        print(f"Wrote XFOIL file to: {fix_path}")
        
        # Run XFOIL
        cp_x, cp_values, coefficients = run_xfoil(fix_path, reynolds, alpha)
        
        return {
            "success": True,
            "message": "Analysis completed successfully",
            "coords_before": raw_coords,
            "coords_after": fixed_coords,
            "num_points": len(fixed_coords),
            "cp_x": cp_x,
            "cp_values": cp_values,
            "coefficients": coefficients
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup temp files
        for p in [raw_path, fix_path]:
            if os.path.exists(p):
                os.remove(p)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)