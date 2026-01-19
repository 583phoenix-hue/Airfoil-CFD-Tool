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

if platform.system() == "Windows":
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil.exe")
    IS_WINDOWS = True
    TMP_DIR = os.getcwd() # Windows uses current dir
else:
    XFOIL_EXE = os.getenv("XFOIL_PATH", "xfoil")
    IS_WINDOWS = False
    TMP_DIR = "/tmp" # Linux uses /tmp for stability

def parse_dat_file(file_path: str):
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
                    except ValueError: continue
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
    return coords

def reorder_to_xfoil_standard(coords):
    if len(coords) < 3: return coords
    le_idx = min(range(len(coords)), key=lambda i: coords[i][0])
    upper = [p for p in coords[:le_idx+1]]
    lower = [p for p in coords[le_idx:]]
    return upper + lower[1:]

def extract_aerodynamic_coefficients(stdout: str):
    coefficients = {}
    patterns = {'CL': r'CL\s*=\s*([-+]?\d*\.?\d+)', 'CD': r'CD\s*=\s*([-+]?\d*\.?\d+)', 'CM': r'CM\s*=\s*([-+]?\d*\.?\d+)'}
    for key, pattern in patterns.items():
        match = re.search(pattern, stdout)
        if match: coefficients[key] = float(match.group(1))
    return coefficients

def run_xfoil(coords_file: str, reynolds: float, alpha: float):
    # Create unique filenames to prevent collisions on the server
    run_id = str(uuid.uuid4())[:8]
    cp_out_path = os.path.join(TMP_DIR, f"cp_{run_id}.txt")
    
    # OS-SPECIFIC COMMANDS
    if IS_WINDOWS:
        commands = [f"LOAD {coords_file}", "PANE", "OPER", f"VISC {reynolds}", 
                    "ITER 100", f"ALFA {alpha}", f"CPWR {cp_out_path}", "QUIT"]
    else:
        # Headless mode for Render
        commands = ["PLOP", "G", "", f"LOAD {coords_file}", "PANE", "OPER", 
                    f"VISC {reynolds}", "ITER 100", f"ALFA {alpha}", f"CPWR {cp_out_path}", "", "QUIT"]

    try:
        input_str = "\n".join(commands) + "\n"
        proc = subprocess.Popen(
            [XFOIL_EXE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=TMP_DIR
        )
        stdout, stderr = proc.communicate(input=input_str, timeout=30)
        time.sleep(0.2) # Wait for file sync

        if not os.path.exists(cp_out_path):
            print(f"XFOIL FAIL. STDOUT: {stdout}") # This will show in Render Logs
            raise Exception("XFOIL did not generate results. Check geometry format.")

        cp_x, cp_values = [], []
        with open(cp_out_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2 and not any(c.isalpha() for c in parts[0]):
                    try:
                        cp_x.append(float(parts[0]))
                        cp_values.append(float(parts[1]))
                    except: continue
        
        # Cleanup
        if os.path.exists(cp_out_path): os.remove(cp_out_path)
        
        return cp_x, cp_values, extract_aerodynamic_coefficients(stdout)

    except Exception as e:
        if 'proc' in locals(): proc.kill()
        raise e

@app.post("/upload_airfoil/")
async def upload_airfoil(file: UploadFile, reynolds: float = Form(...), alpha: float = Form(...)):
    run_id = str(uuid.uuid4())[:8]
    raw_path = os.path.join(TMP_DIR, f"raw_{run_id}.dat")
    fix_path = os.path.join(TMP_DIR, f"fix_{run_id}.dat")
    
    try:
        content = await file.read()
        with open(raw_path, "wb") as f: f.write(content)
        
        raw_coords = parse_dat_file(raw_path)
        fixed_coords = reorder_to_xfoil_standard(raw_coords)
        
        with open(fix_path, "w") as f:
            f.write("AIRFOIL\n")
            for x, y in fixed_coords: f.write(f" {x:.6f} {y:.6f}\n")
        
        cp_x, cp_values, coefficients = run_xfoil(fix_path, reynolds, alpha)
        
        return {"success": True, "cp_x": cp_x, "cp_values": cp_values, "coefficients": coefficients, 
                "coords_before": raw_coords, "coords_after": fixed_coords}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in [raw_path, fix_path]:
            if os.path.exists(p): os.remove(p)