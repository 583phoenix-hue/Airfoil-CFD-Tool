import subprocess
import os
import re
import platform
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Student Airfoil CFD Tool")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auto-detect XFOIL executable based on OS
if platform.system() == "Windows":
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil.exe")
else:  # Linux or Mac
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil")

def parse_dat_file(file_path: str):
    """Parse airfoil coordinates from .dat file."""
    coords = []
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
            # Skip header and empty lines
            for line in lines[1:]:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        x, y = float(parts[0]), float(parts[1])
                        # Validate coordinate range
                        if -0.1 <= x <= 1.1 and -0.5 <= y <= 0.5:
                            coords.append([x, y])
                    except ValueError:
                        continue
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
    
    if len(coords) < 10:
        raise HTTPException(status_code=400, detail="Insufficient valid coordinates in file")
    
    return coords

def reorder_to_xfoil_standard(coords):
    """
    Reorder coordinates to XFOIL standard: TE -> Upper -> LE -> Lower -> TE.
    Handles symmetric and under-cambered airfoils correctly.
    """
    if len(coords) < 3:
        return coords
    
    # Find leading edge (minimum x coordinate)
    le_idx = min(range(len(coords)), key=lambda i: coords[i][0])
    
    # Check if already in correct format by examining ordering
    # If first point has larger x than last, likely already TE->LE->TE format
    if coords[0][0] > coords[le_idx][0] and coords[-1][0] > coords[le_idx][0]:
        # Appears to be in TE->LE->TE format already
        # Split at leading edge
        upper = coords[:le_idx+1]
        lower = coords[le_idx:]
        
        # Verify upper goes TE->LE (decreasing x)
        if len(upper) > 1 and upper[0][0] < upper[-1][0]:
            upper.reverse()
        
        # Verify lower goes LE->TE (increasing x)  
        if len(lower) > 1 and lower[0][0] > lower[-1][0]:
            lower.reverse()
            
        return upper + lower[1:]  # Avoid duplicate LE point
    
    # Otherwise, split based on position relative to chord line
    # Calculate the chord line from TE to LE
    le_x, le_y = coords[le_idx]
    
    # Find trailing edge (maximum x, or average if multiple points)
    te_points = [p for p in coords if p[0] > le_x + 0.8 * (max(c[0] for c in coords) - le_x)]
    if te_points:
        te_y = sum(p[1] for p in te_points) / len(te_points)
    else:
        te_y = coords[0][1]  # Fallback
    
    # Function to determine if point is above chord line
    def above_chord(point):
        x, y = point
        # Linear interpolation along chord line
        if abs(coords[0][0] - le_x) < 1e-6:
            return y >= le_y
        chord_y = le_y + (te_y - le_y) * (x - le_x) / (coords[0][0] - le_x)
        return y >= chord_y
    
    upper = []
    lower = []
    
    for point in coords:
        if above_chord(point):
            upper.append(point)
        else:
            lower.append(point)
    
    # Sort upper: TE to LE (descending x)
    upper.sort(key=lambda p: p[0], reverse=True)
    # Sort lower: LE to TE (ascending x)
    lower.sort(key=lambda p: p[0])
    
    return upper + lower

def extract_aerodynamic_coefficients(stdout: str):
    """Extract CL, CD, and other coefficients from XFOIL output."""
    coefficients = {}
    
    # Pattern for CL, CD, CDp, CM
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
    cp_out = "c.txt"
    if os.path.exists(cp_out):
        os.remove(cp_out)

    commands = [
        "PLOP", "G", "",        # Disable graphics
        f"LOAD {coords_file}",
        "PANE",                 # Regenerate panels
        "OPER",
        f"VISC {reynolds}",
        "ITER 200",             # Max iterations
        f"ALFA {alpha}",
        f"CPWR {cp_out}",       # Write pressure coefficient
        "",
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
            bufsize=1
        )
        
        stdout, stderr = proc.communicate(input=input_str, timeout=30)
        
        # Extract aerodynamic coefficients
        coefficients = extract_aerodynamic_coefficients(stdout)
        
        # Check for convergence
        if "VISCAL:  Convergence failed" in stdout:
            raise Exception("XFOIL convergence failed. Try different angle of attack or Reynolds number.")
        
        # Parse Cp data
        cp_x, cp_values = [], []
        if os.path.exists(cp_out):
            with open(cp_out, "r") as f:
                for line in f:
                    clean = line.strip()
                    if not clean or any(c.isalpha() for c in clean) or clean.startswith("#"):
                        continue
                    parts = clean.split()
                    if len(parts) >= 2:
                        try:
                            cp_x.append(float(parts[0]))
                            cp_values.append(float(parts[1]))
                        except:
                            continue
            os.remove(cp_out)
        else:
            raise Exception("XFOIL failed to generate Cp file. Check airfoil geometry.")

        if not cp_x:
            raise Exception("No pressure data generated. Simulation may have failed.")

    except subprocess.TimeoutExpired:
        if 'proc' in locals():
            proc.kill()
        raise Exception("XFOIL process timeout. Try simpler geometry or different parameters.")
    except FileNotFoundError:
        raise Exception(f"XFOIL executable not found: {XFOIL_EXE}")
    
    return cp_x, cp_values, coefficients

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "running", "message": "Student Airfoil CFD Tool API"}

@app.post("/upload_airfoil/")
async def upload_airfoil(
    file: UploadFile,
    reynolds: float = Form(...),
    alpha: float = Form(...),
):
    """
    Upload airfoil .dat file and run XFOIL analysis.
    
    Parameters:
    - file: Airfoil coordinates in .dat format
    - reynolds: Reynolds number (1000 to 10,000,000)
    - alpha: Angle of attack in degrees (-20 to 20)
    """
    # Validate inputs
    if not 1000 <= reynolds <= 10_000_000:
        raise HTTPException(status_code=400, detail="Reynolds number must be between 1,000 and 10,000,000")
    
    if not -20 <= alpha <= 20:
        raise HTTPException(status_code=400, detail="Angle of attack must be between -20° and 20°")
    
    raw_path = "raw.dat"
    fix_path = "fix.dat"
    
    try:
        # Save uploaded file
        content = await file.read()
        with open(raw_path, "wb") as f:
            f.write(content)
        
        # Parse and reorder coordinates
        raw_coords = parse_dat_file(raw_path)
        fixed_coords = reorder_to_xfoil_standard(raw_coords)
        
        # Write properly formatted file for XFOIL
        with open(fix_path, "w") as f:
            f.write("AIRFOIL\n")
            for x, y in fixed_coords:
                f.write(f" {x:.6f} {y:.6f}\n")
        
        # Run XFOIL
        cp_x, cp_values, coefficients = run_xfoil(fix_path, reynolds, alpha)
        
        return {
            "success": True,
            "coords_before": raw_coords,
            "coords_after": fixed_coords,
            "cp_x": cp_x,
            "cp_values": cp_values,
            "coefficients": coefficients,
            "metadata": {
                "reynolds": reynolds,
                "alpha": alpha,
                "num_points": len(fixed_coords)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup temporary files
        for p in [raw_path, fix_path]:
            if os.path.exists(p):
                os.remove(p)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)