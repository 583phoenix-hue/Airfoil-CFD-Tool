import subprocess
import os
import re
import platform
import time
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
    IS_WINDOWS = True
else:  # Linux or Mac (Render)
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil")
    IS_WINDOWS = False

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
    if coords[0][0] > coords[le_idx][0] and coords[-1][0] > coords[le_idx][0]:
        upper = coords[:le_idx+1]
        lower = coords[le_idx:]
        if len(upper) > 1 and upper[0][0] < upper[-1][0]: upper.reverse()
        if len(lower) > 1 and lower[0][0] > lower[-1][0]: lower.reverse()
        return upper + lower[1:]
    
    le_x, le_y = coords[le_idx]
    te_points = [p for p in coords if p[0] > le_x + 0.8 * (max(c[0] for c in coords) - le_x)]
    te_y = sum(p[1] for p in te_points) / len(te_points) if te_points else coords[0][1]
    
    def above_chord(point):
        x, y = point
        if abs(coords[0][0] - le_x) < 1e-6: return y >= le_y
        chord_y = le_y + (te_y - le_y) * (x - le_x) / (coords[0][0] - le_x)
        return y >= chord_y
    
    upper = [p for p in coords if above_chord(p)]
    lower = [p for p in coords if not above_chord(p)]
    upper.sort(key=lambda p: p[0], reverse=True)
    lower.sort(key=lambda p: p[0])
    return upper + lower

def extract_aerodynamic_coefficients(stdout: str):
    coefficients = {}
    patterns = {
        'CL': r'CL\s*=\s*([-+]?\d*\.?\d+)',
        'CD': r'CD\s*=\s*([-+]?\d*\.?\d+)',
        'CDp': r'CDp\s*=\s*([-+]?\d*\.?\d+)',
        'CM': r'CM\s*=\s*([-+]?\d*\.?\d+)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, stdout)
        if match: coefficients[key] = float(match.group(1))
    return coefficients

def run_xfoil(coords_file: str, reynolds: float, alpha: float):
    # Use absolute paths to ensure the OS finds the files in the cloud
    work_dir = os.getcwd()
    cp_out = "c.txt"
    cp_out_path = os.path.join(work_dir, cp_out)
    abs_coords = os.path.abspath(coords_file)
    
    if os.path.exists(cp_out_path):
        os.remove(cp_out_path)

    # OS-SPECIFIC COMMANDS
    if IS_WINDOWS:
        commands = [
            f"LOAD {abs_coords}",
            "PANE",
            "OPER",
            f"VISC {reynolds}",
            "ITER 200",
            f"ALFA {alpha}",
            f"CPWR {cp_out}",
            "QUIT"
        ]
    else:
        # Render/Linux requires 'PLOP G' to be headless
        commands = [
            "PLOP", "G", "", # Disable graphics toggle
            f"LOAD {abs_coords}",
            "PANE",
            "OPER",
            f"VISC {reynolds}",
            "ITER 200",
            f"ALFA {alpha}",
            f"CPWR {cp_out}",
            "", # Confirm write
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
            cwd=work_dir
        )
        
        stdout, stderr = proc.communicate(input=input_str, timeout=40)
        
        # Give the filesystem a moment to sync
        time.sleep(0.3)
        
        coefficients = extract_aerodynamic_coefficients(stdout)
        
        if "VISCAL:  Convergence failed" in stdout:
            raise Exception("XFOIL convergence failed. Try a lower angle or different Reynolds.")
        
        cp_x, cp_values = [], []
        if os.path.exists(cp_out_path):
            with open(cp_out_path, "r") as f:
                for line in f:
                    clean = line.strip()
                    if not clean or any(c.isalpha() for c in clean) or clean.startswith("#"): continue
                    parts = clean.split()
                    if len(parts) >= 2:
                        try:
                            cp_x.append(float(parts[0]))
                            cp_values.append(float(parts[1]))
                        except: continue
            os.remove(cp_out_path)
        else:
            # For debugging on Render:
            print(f"XFOIL STDOUT: {stdout}")
            raise Exception("XFOIL failed to generate Cp file. Geometry may be invalid.")

        return cp_x, cp_values, coefficients

    except subprocess.TimeoutExpired:
        if 'proc' in locals(): proc.kill()
        raise Exception("XFOIL process timeout.")
    except Exception as e:
        raise e

@app.post("/upload_airfoil/")
async def upload_airfoil(
    file: UploadFile,
    reynolds: float = Form(...),
    alpha: float = Form(...),
):
    raw_path = os.path.abspath("raw.dat")
    fix_path = os.path.abspath("fix.dat")
    
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