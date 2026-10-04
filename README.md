# AeroLab — Web-Based Airfoil Aerodynamic Analysis Tool

[![Live Demo](https://img.shields.io/badge/Live%20Demo-aerolab--app.onrender.com-blue)](https://aerolab-app.onrender.com/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/doi/10.5281/zenodo.20740325.svg)](https://doi.org/10.5281/zenodo.20740325)

AeroLab is a free, browser-based aerodynamics toolkit built on the industry-standard [XFOIL](https://web.mit.edu/drela/Public/web/xfoil/) panel method solver. Students, researchers and aerospace enthusiasts can analyse 2D airfoil sections, design airfoils from a target pressure distribution, and estimate aeroelastic limits (divergence, control reversal, flutter), all without installing any software.

**Live tool:** https://aerolab-app.onrender.com/

---

## Features

### Airfoil Analysis
- **Four modes**: single analysis, angle-of-attack sweep, batch upload (up to 10 files), and side-by-side comparison of two airfoils
- **Results**: lift (CL), drag (CD), pitching moment (Cm), pressure distribution (Cp), boundary-layer data and transition points
- **Controls**: Reynolds number, Mach number, NCrit (turbulence level), viscous or inviscid mode
- **Robust `.dat` file parser**: handles Selig and Lednicer formats, corrects winding order, removes duplicate leading/trailing edge points, and fixes common formatting errors that make stock XFOIL reject files
- **Three-strategy solver**: viscous → viscous with geometry smoothing → inviscid fallback, so difficult geometries still return a result
- **Exports**: CSV tables, boundary-layer CSV, and publication-style polar PNGs
- **Built-in example airfoils**: NACA 0012, NACA 4412, Clark Y, Eppler 387, Selig S1223

### Interactive Wind Tunnel
- Real-time GPU-accelerated D2Q9 Lattice-Boltzmann flow simulation in the browser
- Velocity, pressure and vorticity views; velocity shown in multiples of freestream speed (×U∞)
- Live angle-of-attack and Reynolds-number control, showing the Reynolds number actually simulated
- Smoke and particle-trail visualisation, stall indicator, PNG export, and a side-by-side tunnel in compare mode

### Inverse Design
- Design an airfoil that produces a target pressure distribution (Cp), using SU2-style Cp matching driven by XFOIL
- Draw the target in an interactive Cp curve editor, or upload a Cp file
- Start from a seed airfoil (NACA 0012 by default, or your own) with a minimum-thickness constraint
- Live progress bar, with the final design checked by a viscous XFOIL run

### Aeroelasticity
- **Static divergence**: divergence speed from a viscous XFOIL lift curve, compared with the linear estimate
- **Control reversal**: aileron reversal speed, with flap effectiveness from XFOIL or thin-airfoil theory
- **Flutter**: V-g analysis with Theodorsen unsteady aerodynamics

---

## Architecture

| Component | Technology |
|---|---|
| Frontend | React + Vite (`aerolab-web/`), served by nginx |
| Backend | FastAPI + XFOIL (`main.py`) |
| Database | PostgreSQL (analysis counter) |
| Deployment | Render: frontend and backend as Docker services |

The wind tunnel runs entirely in the visitor's browser (WebGL). All XFOIL work happens on the backend.

The previous Streamlit frontend (`app.py`, `pages/`) is kept in the repository for reference but is no longer deployed.

---

## Local Development

Step-by-step Windows instructions are in [Instructions/local_setup.md](Instructions/local_setup.md).

### Prerequisites

- Python 3.11+
- Node.js 18+
- XFOIL 6.99:
  - Debian/Ubuntu: `sudo apt install xfoil`. The packaged build crashes on a harmless floating-point trap when graphics are off; `Dockerfile.backend` shows the one-line workaround, or run the backend with Docker
  - Windows: place `xfoil.exe` next to `main.py`, or set `XFOIL_PATH`
- PostgreSQL (optional; only needed for the analysis counter)

### Backend

```bash
git clone https://github.com/583phoenix-hue/Airfoil-CFD-Tool.git
cd Airfoil-CFD-Tool

pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

The backend runs at `http://localhost:8000` (check `http://localhost:8000/health`).

### Frontend

In a second terminal:

```bash
cd aerolab-web
npm install
cp .env.example .env.local      # points the site at http://localhost:8000
npm run dev
```

The site runs at `http://localhost:5173`. Without `.env.local` it uses the live backend.

### Environment Variables

| Variable | Where | Purpose |
|---|---|---|
| `VITE_BACKEND_URL` | Frontend (`aerolab-web/.env.local`, or at build time) | Backend address. Defaults to `https://aerolab-backend.onrender.com` |
| `DATABASE_URL` | Backend | PostgreSQL URL for the analysis counter (optional) |
| `XFOIL_PATH` | Backend | Path to the XFOIL executable, if it isn't `xfoil` / `xfoil.exe` |
| `ALLOWED_ORIGINS` | Backend | Comma-separated CORS origins (default: all) |

### Docker

```bash
# Backend (includes XFOIL)
docker build -f Dockerfile.backend -t aerolab-backend .
docker run -p 8000:8000 -e DATABASE_URL=... aerolab-backend

# Frontend (builds the React site and serves it with nginx)
docker build -f Dockerfile.frontend -t aerolab-frontend .
docker run -p 8080:10000 aerolab-frontend
```

The frontend is then at `http://localhost:8080`.

---

## Running Tests

```bash
pip install pytest
pytest test_main.py -v
```

Tests cover the `.dat` file parser (Selig/Lednicer detection, winding order correction, duplicate point removal) and the XFOIL output coefficient extractor.

---

## Usage

1. Visit the [live tool](https://aerolab-app.onrender.com/) or run it locally
2. Choose a module: **Airfoil Analysis**, **Inverse Design** or **Aeroelasticity**
3. Pick a built-in example airfoil, or upload a `.dat` file from a database such as the [UIUC Airfoil Coordinate Database](https://m-selig.ae.illinois.edu/ads/coord_database.html) or [Airfoil Tools](http://airfoiltools.com/). The parser fixes malformed files automatically
4. Set the flow conditions (Reynolds number, angle of attack or sweep range, and so on)
5. Run the analysis, view the charts, and download the results

---

## Supported Airfoil Coordinate Formats

- **Selig format**: a single contiguous loop: TE → upper surface → LE → lower surface → TE
- **Lednicer format**: two separate sections (upper and lower), each running LE → TE

Common issues corrected automatically:
- Incorrect winding order
- Duplicate leading edge or trailing edge points
- Mixed whitespace (tabs, multiple spaces)
- Header lines and comment lines

---

## Input Limits

| Parameter | Minimum | Maximum |
|---|---|---|
| Reynolds number | 10,000 | 10,000,000 |
| Angle of attack | −10° | +20° |
| Mach number | 0 | 0.75 |
| Airfoil file size | — | 1 MB (10–500 points) |

---

## Acknowledgements

AeroLab is built on [XFOIL](https://web.mit.edu/drela/Public/web/xfoil/) by Professor Mark Drela (MIT), the industry-standard low Reynolds number airfoil analysis code. The interactive wind tunnel is adapted from the [Kutta](https://github.com/crgimenes/kutta) open-source LBM flow visualiser by Cesar Gimenes (MIT License).

---

## Author

**Pranav Nathan**  
Aspiring Aerospace Engineer  
GitHub: [@583phoenix-hue](https://github.com/583phoenix-hue)  
Email: pranav09nathan@gmail.com

---

## License

This project is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE) for details.

---

## Citation

If you use AeroLab in your research or teaching, please cite it using the metadata in [CITATION.cff](CITATION.cff) (GitHub's "Cite this repository" button), or the associated software paper (forthcoming).
