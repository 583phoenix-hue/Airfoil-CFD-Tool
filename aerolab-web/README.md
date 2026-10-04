# AeroLab web (React)

Static React frontend for AeroLab. It replaces the Streamlit frontend
(`aerolab-app`) and talks to the existing FastAPI backend (`aerolab-backend`).
Everything interactive runs in the visitor's browser; the host only serves
files, so many students at once don't use any server memory.

## Pages

| Route | Page |
|---|---|
| `/`, `/about`, `/choose` | Home, About, Choose a tool |
| `/analysis` | Airfoil Analysis: single, AOA sweep, batch (up to 10), compare two; Cp/geometry charts, parser output, CSV/PNG downloads, single and side-by-side LBM wind tunnels |
| `/inverse-design` | Inverse Design: drag editor seeded from the seed airfoil's Cp, Cp file upload with preview, seed upload, minimum thickness, results |
| `/aeroelasticity`, `/aeroelasticity/:module` | Module picker; divergence, control reversal and flutter runs |

Where the pieces came from:

- `public/lbm/single.html`, `public/lbm/dual.html`: the wind tunnel (v2:
  simulated Re shown, ×U∞ colour bar, particle trails). `single_v1.html` and
  `dual_v1.html` are the previous version, kept for reverting.
- `public/cp_editor.html`: `pages/cp_curve_editor_component/index.html`
  (plus a font link). If you edit that, copy it here too.
- `src/lib/cpParser.js`: a JavaScript port of `pages/cp_target_parser.py`,
  so Cp files are read in the browser. Same rules and messages; checked
  against the Python version on 18 test files.
- `public/examples/`: the bundled example airfoils.
- Charts use Plotly (basic bundle), loaded only on the tool pages.

## Run locally

Requires Node 18+.

```
npm install
cp .env.example .env.local     # optional: point at a local backend
npm run dev                    # http://localhost:5173
```

Without `.env.local` it uses the live backend
(`https://aerolab-backend.onrender.com`).

## Build

```
npm run build                  # static files in dist/
npm run preview                # serve dist/ locally to check the build
```

## Deploy on Render

The site is deployed as a Docker web service (`aerolab-app`) using
`Dockerfile.frontend` in the repository root: it builds this folder and
serves `dist/` with nginx, including the rewrite that makes `/about` etc.
work when opened directly. Push to GitHub and Render redeploys.

`render.yaml` is an alternative for deploying as a Render Static Site
instead (Root Directory `aerolab-web`).

## Backend notes

- CORS: the backend allows all origins by default (`ALLOWED_ORIGINS`
  env var). If you've restricted it on Render, add this site's URL.
- The browser now calls the backend directly, so every student counts as a
  separate visitor to it, and a whole class behind one school network shares
  one IP address. The per-IP rate limits on `/`, `/health` and
  `/analysis_count` were removed in `main.py` for that reason.

- Inverse design and aeroelasticity need `inverse_design.py` and the three
  aeroelasticity modules next to `main.py` on the backend (all in the repo and
  copied by `Dockerfile.backend`). Without them those endpoints return 503
  and the pages say the feature isn't available; Airfoil Analysis keeps working.
