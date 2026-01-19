import subprocess
import os
import re
import platform
import time
import uuid
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

# Auto-detect XFOIL executable based on OS and set temporary directory
if platform.system() == "Windows":
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil.exe")
    IS_WINDOWS = True
    TMP_DIR = os.getcwd()
else:  # Linux or Mac (Render)
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil")
    IS_WINDOWS = False
    TMP_DIR = "/tmp"

def parse_dat_file(file_path: str):
    """Parse airfoil coordinates from .dat file."""
    coords = []
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
            for line in lines[1:]:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        x, y = float(parts[0]), float(parts[1])
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
    """Reorder coordinates to XFOIL standard: TE -> Upper -> LE -> Lower -> TE."""
    if len(coords) < 3:
        return coords
    le_idx = min(range(len(coords)), key=lambda i: coords[i][0])
    upper = coords[:le_idx+1]
    lower = coords[le_idx:]
    return upper + lower[1:]

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
    cp_out_path = os.path.join(TMP_DIR, f"cp_{run_id}.txt")
    
    if os.path.exists(cp_out_path):
        os.remove(cp_out_path)

    # OS-SPECIFIC COMMANDS
    if IS_WINDOWS:
        commands = [
            f"LOAD {coords_file}",
            "PANE",
            "OPER",
            f"VISC {reynolds}",
            "ITER 100",
            f"ALFA {alpha}",
            f"CPWR {cp_out_path}",
            "QUIT"
        ]
    else:
        # Optimized headless sequence for Render
        commands = [
            "PLOP", "G", "", 
            f"LOAD {coords_file}",
            "PANE",
            "OPER",
            f"VISC {reynolds}",
            "ITER 200",
            f"ALFA {alpha}",
            f"CPWR {cp_out_path}",
            "", # Confirm file write
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
        
        stdout, stderr = proc.communicate(input=input_str, timeout=45)
        
        # ESSENTIAL: Give the filesystem a moment to write the file
        time.sleep(0.5)
        
        # Diagnostic Log: This will show up in your Render logs
        if not os.path.exists(cp_out_path):
            print(f"--- XFOIL TERMINAL OUTPUT ---\n{stdout[-1000:]}")
            print(f"--- XFOIL ERROR OUTPUT ---\n{stderr}")
            if "VISCAL:  Convergence failed" in stdout:
                raise Exception("XFOIL convergence failed. Try different parameters.")
            else:
                raise Exception("XFOIL failed to generate Cp file. Check terminal output in logs.")

        coefficients = extract_aerodynamic_coefficients(stdout)
        
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
                    except:
                        continue
        
        # Final cleanup
        if os.path.exists(cp_out_path):
            os.remove(cp_out_path)
            
        return cp_x, cp_values, coefficients

    except subprocess.TimeoutExpired:
        if 'proc' in locals(): proc.kill()
        raise Exception("XFOIL process timeout.")
    except Exception as e:
        raise e

@app.post("/upload_airfoil/")
async def upload_airfoil(file: UploadFile, reynolds: float = Form(...), alpha: float = Form(...)):
    run_id = str(uuid.uuid4())[:8]
    raw_path = os.path.join(TMP_DIR, f"raw_{run_id}.dat")
    fix_path = os.path.join(TMP_DIR, f"fix_{run_id}.dat")
    
    try:
        content = await file.read()
        with open(raw_path, "wb") as f:
            f.write(content)
        
        raw_coords = parse_dat_file(raw_path)
        fixed_coords = reorder_to_xfoil_standard(raw_coords)
        
        with open(fix_path, "w") as f:
            f.write("AIRFOIL\n")
            for x, y in fixed_coords:
                f.write(f" {x:.6f} {y:.6f}\n")
        
        cp_x, cp_values, coefficients = run_xfoil(fix_path, reynolds, alpha)
        
        return {
            "success": True,
            "coords_before": raw_coords,
            "coords_after": fixed_coords,
            "cp_x": cp_x,
            "cp_values": cp_values,
            "coefficients": coefficients
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in [raw_path, fix_path]:
            if os.path.exists(p): os.remove(p)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)