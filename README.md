# AeroLab — Web-Based Airfoil Aerodynamic Analysis Tool

[![Live Demo](https://img.shields.io/badge/Live%20Demo-aerolab--app.onrender.com-blue)](https://aerolab-app.onrender.com/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

AeroLab is a free, browser-based aerodynamic analysis tool built on the industry-standard [XFOIL](https://web.mit.edu/drela/Public/web/xfoil/) panel method solver. It allows students, researchers, and aerospace enthusiasts to analyse 2D airfoil sections — including lift coefficient (CL), drag coefficient (CD), pitching moment (Cm), and pressure distribution (Cp) — without installing any software.

**Live tool:** https://aerolab-app.onrender.com/

---

## Features

- **Robust `.dat` file parser** — automatically handles Selig and Lednicer coordinate formats, corrects winding order, removes duplicate leading/trailing edge points, and resolves common formatting errors that cause stock XFOIL to reject files
- **Potential flow visualisation** — animated streamlines and speed heatmap computed via an independent 160-panel vortex panel method implementation, with Kutta condition enforcement and ill-conditioning fallback
- **Boundary layer overlay** — displacement thickness envelope (δ*) and laminar-to-turbulent transition locations parsed from XFOIL viscous DUMP output
- **Three-strategy solver** — viscous → viscous with geometry smoothing → inviscid fallback, ensuring a result is returned even for difficult airfoil geometries
- **No installation required** — runs entirely in the browser; users paste coordinates and input Reynolds number and angle of attack

---

## Architecture

| Component | Technology |
|---|---|
| Frontend | Streamlit (Python) |
| Backend | FastAPI + XFOIL |
| Database | PostgreSQL (analysis counter) |
| Deployment | Streamlit Community Cloud (frontend) + Render (backend) |

---

## Local Development

### Prerequisites

- Python 3.11+
- XFOIL installed and accessible on your PATH (`sudo apt install xfoil` on Debian/Ubuntu)
- PostgreSQL (optional — only needed for the analysis counter)

### Backend

```bash
git clone https://github.com/583phoenix-hue/Airfoil-CFD-Tool.git
cd Airfoil-CFD-Tool

pip install -r requirements.txt

# Run backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Frontend

Open a **second terminal** (the backend must be running in the first):

```bash
# Linux/macOS
export LOCAL_DEV=true
export BACKEND_URL=http://localhost:8000
export DATABASE_URL=postgresql://user:password@your-host/dbname?sslmode=require
streamlit run app.py
```

```cmd
:: Windows CMD
set LOCAL_DEV=true
set BACKEND_URL=http://localhost:8000
set DATABASE_URL=postgresql://user:password@your-host/dbname?sslmode=require
streamlit run app.py
```

Frontend will be available at `http://localhost:8501`.

> **Note:** These environment variables are session-only and must be set each time you open a new terminal window.

### Environment Variables

| Variable | Local value | Purpose |
|---|---|---|
| `LOCAL_DEV` | `true` | Bypasses Render backend health check |
| `BACKEND_URL` | `http://localhost:8000` | Points frontend to local backend |
| `DATABASE_URL` | your PostgreSQL URL | Required for analysis counter (optional) |

Do **not** set these in production — the deployed app defaults to the correct Render URLs automatically.

### Docker

```bash
# Backend
docker build -f Dockerfile.backend -t aerolab-backend .
docker run -p 8000:8000 aerolab-backend

# Frontend
docker build -f Dockerfile.frontend -t aerolab-frontend .
docker run -p 8501:8501 aerolab-frontend
```

---

## Running Tests

```bash
pip install pytest
pytest test_main.py -v
```

Tests cover the `.dat` file parser (Selig/Lednicer format detection, winding order correction, duplicate point removal) and the XFOIL output coefficient extractor.

---

## Usage

1. Visit the [live tool](https://aerolab-app.onrender.com/) or run locally
2. Obtain an airfoil coordinate file (`.dat`) from a database such as the [UIUC Airfoil Coordinate Database](https://m-selig.ae.illinois.edu/ads/coord_database.html) or [Airfoil Tools](http://airfoiltools.com/)
3. Paste or upload the `.dat` file — the parser handles malformed files automatically
4. Set Reynolds number (10,000 – 10,000,000) and angle of attack (−10° to +20°)
5. Click **Analyse** to run XFOIL and view results

---

## Supported Airfoil Coordinate Formats

AeroLab's parser handles both common `.dat` formats:

- **Selig format** — single contiguous loop: TE → upper surface → LE → lower surface → TE
- **Lednicer format** — two separate sections (upper and lower), each running LE → TE

Common issues corrected automatically:
- Incorrect winding order
- Duplicate leading edge or trailing edge points
- Mixed whitespace (tabs, multiple spaces)
- Header lines and comment lines

---

## Reynolds Number and Angle of Attack Limits

| Parameter | Minimum | Maximum |
|---|---|---|
| Reynolds number | 10,000 | 10,000,000 |
| Angle of attack | −10° | +20° |

---

## Acknowledgements

AeroLab is built on [XFOIL](https://web.mit.edu/drela/Public/web/xfoil/) by Professor Mark Drela (MIT), the industry-standard low Reynolds number airfoil analysis code.

---

## Author

**Nathan Pranav**  
Aspiring Aerospace Engineer  
GitHub: [@583phoenix-hue](https://github.com/583phoenix-hue)

---

## License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for details.

---

## Citation

If you use AeroLab in your research or teaching, please cite the associated software paper (forthcoming).
