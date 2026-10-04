# AeroLab — Local Development Setup (Windows)

## Prerequisites

Install these first:

- **Python 3.11** (with pip)
- **Node.js 18 or newer** (includes npm)
- **Git**
- **XFOIL 6.99 for Windows**: download it from the [XFOIL website](https://web.mit.edu/drela/Public/web/xfoil/) and put `xfoil.exe` in the project folder, next to `main.py`. It is ignored by Git, so it is never committed.

---

## Installation

1. Clone the repository (or open your existing copy):

```cmd
git clone https://github.com/583phoenix-hue/Airfoil-CFD-Tool.git
cd Airfoil-CFD-Tool
```

2. Install the backend's Python packages:

```cmd
pip install -r requirements.txt
```

3. Install the frontend's packages (only needed once, and again if `package.json` changes):

```cmd
cd aerolab-web
npm install
copy .env.example .env.local
cd ..
```

`.env.local` points the website at your local backend (`http://localhost:8000`). Delete it to use the live backend instead.

---

## Running Locally

You need **two Command Prompt windows** open at the same time.

### Window 1: backend (FastAPI + XFOIL)

```cmd
cd "path\to\Airfoil-CFD-Tool"
set DATABASE_URL=postgresql://user:password@your-host/dbname?sslmode=require
uvicorn main:app --reload
```

- The backend runs at `http://localhost:8000`. Open `http://localhost:8000/health` to check that it found XFOIL.
- `DATABASE_URL` is optional. Without it everything works, but the analysis counter shows "—".
- `set` only lasts for that window, so set `DATABASE_URL` again each time you open a new one.

### Window 2: frontend (React)

```cmd
cd "path\to\Airfoil-CFD-Tool\aerolab-web"
npm run dev
```

The website runs at `http://localhost:5173` and reloads automatically when you edit files in `aerolab-web/src`.

To check a production build locally:

```cmd
npm run build
npm run preview
```

---

## Environment Variables

| Variable | Set on | Local value | Purpose |
|---|---|---|---|
| `VITE_BACKEND_URL` | Frontend (`aerolab-web/.env.local`) | `http://localhost:8000` | Which backend the website calls |
| `DATABASE_URL` | Backend | your PostgreSQL URL | Analysis counter (optional) |
| `XFOIL_PATH` | Backend | path to `xfoil.exe` | Only if XFOIL isn't next to `main.py` |
| `ALLOWED_ORIGINS` | Backend | — | CORS origins; leave unset to allow all |

---

## Production Deployment (Render)

| Service | Render setup | Dockerfile |
|---|---|---|
| Frontend (React, served by nginx) | Docker web service, `aerolab-app.onrender.com` | `Dockerfile.frontend` |
| Backend (FastAPI + XFOIL) | Docker web service, `aerolab-backend.onrender.com` | `Dockerfile.backend` |

- Both services build from the repository root.
- The backend needs `DATABASE_URL` set in its **Environment** tab for the analysis counter.
- The frontend needs no environment variables; it calls `https://aerolab-backend.onrender.com` by default.
- Push to GitHub and Render redeploys automatically (or use **Manual Deploy → Deploy latest commit**):

```cmd
git add <files>
git commit -m "your message"
git push
```

---

## Project Structure

```
Airfoil-CFD-Tool/
├── main.py                  # Backend API (FastAPI + XFOIL)
├── inverse_design.py        # Inverse design solver (Cp matching)
├── static_divergence.py     # Aeroelasticity: static divergence + shared XFOIL polar layer
├── control_reversal.py      # Aeroelasticity: control reversal
├── flutter_vg.py            # Aeroelasticity: V-g flutter analysis
├── db_utils.py              # PostgreSQL analysis counter
├── requirements.txt         # Python dependencies
├── Dockerfile.backend       # Backend image (XFOIL + uvicorn)
├── Dockerfile.frontend      # Frontend image (React build + nginx)
├── test_main.py             # Parser and XFOIL output tests
├── aerolab-web/             # React frontend
│   ├── src/
│   │   ├── pages/           # Home, Analysis, Inverse Design, Aeroelasticity, About
│   │   ├── components/      # Shared UI, airfoil picker, Cp editor, diagrams
│   │   └── lib/             # Charts, file handling, Cp file parser
│   └── public/
│       ├── lbm/             # Wind tunnel (single and side-by-side)
│       ├── examples/        # Bundled example airfoils
│       └── cp_editor.html   # Interactive Cp curve editor
├── app.py, pages/           # Previous Streamlit frontend (no longer deployed)
└── Instructions/
    └── local_setup.md       # This file
```
