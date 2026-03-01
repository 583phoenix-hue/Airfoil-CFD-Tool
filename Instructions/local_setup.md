\# AeroLab — Local Development Setup



\## Prerequisites

Make sure you have the following installed:

\- Python 3.11

\- pip

\- Git



---



\## Installation



1\. Clone the repository and navigate to the project folder:

```cmd

cd "path\\to\\CFD\_Tool"

```



2\. Install dependencies:

```cmd

pip install -r requirements.txt

```



---



\## Running Locally



You need \*\*two CMD windows\*\* open at the same time.



\### Window 1 — Start the Backend (FastAPI + XFOIL)

```cmd

cd "path\\to\\CFD\_Tool"

uvicorn main:app --reload

```

Backend will be running at: `http://localhost:8000`



\### Window 2 — Start the Frontend (Streamlit)

```cmd

cd "path\\to\\CFD\_Tool"

set LOCAL_DEV=true

set BACKEND_URL=http://localhost:8000

set DATABASE_URL=postgresql://user:password@your-neon-host.neon.tech/neondb?sslmode=require

streamlit run app.py

```

Frontend will be running at: `http://localhost:8501`



> \*\*Important:\*\* You must set `LOCAL_DEV=true`, `BACKEND_URL` and `DATABASE_URL` every time you open a new CMD window. These are session-only environment variables and do not persist.



---



\## Environment Variables



| Variable | Local Value | Purpose |

|---|---|---|

| `LOCAL_DEV` | `true` | Bypasses Render backend health check |

| `BACKEND_URL` | `http://localhost:8000` | Points frontend to local backend |

| `DATABASE_URL` | your PostgreSQL URL | Required for analysis counter |






---



\## Production Deployment



| Service | Platform | Account |

|---|---|---|

| Frontend (Streamlit) | Render Account A | — |

| Backend (FastAPI/XFOIL) | Render Account B | — |



\- Do \*\*not\*\* set `LOCAL_DEV` or `BACKEND_URL` in production — they default to the correct Render URLs automatically.

\- Push to GitHub and Render will auto-redeploy.



```cmd

git add .

git commit -m "your message"

git push

```



---



\## Project Structure



```

CFD\_Tool/

├── app.py                  # Homepage (Streamlit)

├── main.py                 # Backend API (FastAPI + XFOIL)

├── db\_utils.py             # PostgreSQL database utilities

├── requirements.txt        # Python dependencies

├── pages/

│   ├── Airfoil\_Analysis.py # Analysis page

│   └── About.py            # About page

├── .streamlit/

│   └── config.toml         # Streamlit config (hides branding)

└── docs/

&nbsp;   └── local\_setup.md      # This file

```

