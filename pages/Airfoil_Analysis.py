import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import os
import time
from db_utils import increment_analysis_count

# Page configuration
st.set_page_config(page_title="Airfoil Analysis - AeroLab", layout="wide", page_icon="✈️",
                   initial_sidebar_state="collapsed")

# Always hide sidebar completely
st.markdown("""
    <style>
        [data-testid="stSidebarNav"]    {display: none;}
        [data-testid="collapsedControl"] {display: none;}
        section[data-testid="stSidebar"] {display: none;}

        .param-label {
            font-size: 0.82rem;
            font-weight: 600;
            color: #555;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.2rem;
        }
        .panel-title {
            font-size: 1.15rem;
            font-weight: 700;
            color: #667eea;
            padding-bottom: 0.6rem;
            border-bottom: 2px solid #667eea30;
            margin-bottom: 1rem;
        }
        .main-header {
            font-size: 2.8rem;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 0.2rem;
        }
        .sub-header {
            color: #888;
            margin-bottom: 1.5rem;
            font-size: 1rem;
        }
    </style>
""", unsafe_allow_html=True)

# ── Backend Health Check ────────────────────────────────────────────────────
BACKEND_URL = "https://aerolab-backend.onrender.com"

@st.cache_data(ttl=60, show_spinner=False)
def check_backend() -> str:
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=8)
        if "suspended" in r.text.lower() or "service has been suspended" in r.text.lower():
            return "suspended"
        return "online" if r.status_code == 200 else "offline"
    except requests.exceptions.Timeout:
        return "offline"
    except Exception:
        return "offline"

backend_status = check_backend()

# Block the entire page if backend is not online
if backend_status != "online":
    if st.button("← Back to Home"):
        st.switch_page("app.py")
    st.markdown("<br>", unsafe_allow_html=True)
    if backend_status == "suspended":
        st.error("🛠️ Solver Suspended")
        st.warning(
            "The XFOIL backend has reached its monthly compute limit on Render's free tier. "
            "It will automatically reset at the start of next month."
        )
    else:
        st.warning("⏳ Solver Waking Up...")
        st.info(
            "The XFOIL backend is currently starting up (Render free tier spins down after inactivity). "
            "Please wait ~30 seconds and refresh the page."
        )
    st.stop()
# ───────────────────────────────────────────────────────────────────────────

# Initialize session state
if 'results' not in st.session_state:
    st.session_state.results = None
if 'last_params' not in st.session_state:
    st.session_state.last_params = None

# Cached function for API calls
@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def run_xfoil_analysis(file_content: bytes, filename: str, reynolds: float, alpha: float, backend_url: str):
    url = f"{backend_url}/upload_airfoil/"
    files = {"file": (filename, file_content, "text/plain")}
    data = {"reynolds": reynolds, "alpha": alpha}
    max_retries = 3
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(url, files=files, data=data, timeout=90)
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    raise Exception(f"Server busy. Retrying in {retry_delay * (attempt + 1)}s... (Attempt {attempt + 1}/{max_retries})")
                else:
                    raise Exception("Server is rate-limited. Please wait 60 seconds and try again.")
            if response.status_code != 200:
                raise Exception(f"Server Error ({response.status_code}): {response.text}")
            return response.json()
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                continue
            raise Exception("Request timeout - backend is taking too long (>90s)")
        except requests.exceptions.ConnectionError:
            raise Exception("Cannot connect to backend server. It may be starting up.")
        except Exception as e:
            error_msg = str(e)
            if "Retrying" in error_msg and attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise Exception(error_msg)
    raise Exception("Max retries exceeded")

# ── Layout: narrow left panel + wide right content ──────────────────────────
left_col, right_col = st.columns([1, 3])

with left_col:
    st.markdown('<div class="panel-title">⚙️ Parameters</div>', unsafe_allow_html=True)

    if st.button("← Home", use_container_width=True):
        st.switch_page("app.py")

    st.markdown("<br>", unsafe_allow_html=True)

    # Reynolds Number
    st.markdown('<p class="param-label">Reynolds Number</p>', unsafe_allow_html=True)
    reynolds_preset = st.selectbox(
        "Reynolds Preset",
        ["Custom", "Model Aircraft (50k)", "Small UAV (100k)", "Light Aircraft (500k)",
         "Glider (1M)", "Small Plane (3M)", "Airliner (6M)"],
        index=3,
        label_visibility="collapsed"
    )
    reynolds_values = {
        "Custom": 500_000,
        "Model Aircraft (50k)": 50_000,
        "Small UAV (100k)": 100_000,
        "Light Aircraft (500k)": 500_000,
        "Glider (1M)": 1_000_000,
        "Small Plane (3M)": 3_000_000,
        "Airliner (6M)": 6_000_000
    }
    default_re = reynolds_values.get(reynolds_preset, 500_000)
    reynolds = st.number_input(
        "Reynolds Number Value",
        min_value=1_000,
        max_value=10_000_000,
        value=default_re,
        step=10_000,
        format="%d",
        help="Higher Reynolds = less viscous effects",
        label_visibility="collapsed"
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # Angle of Attack
    st.markdown('<p class="param-label">Angle of Attack</p>', unsafe_allow_html=True)
    alpha = st.slider(
        "Angle of Attack",
        min_value=-20.0,
        max_value=20.0,
        value=5.0,
        step=0.5,
        help="Angle between chord line and freestream",
        label_visibility="collapsed"
    )
    st.caption(f"Selected: **{alpha}°**")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("---")

    with st.expander("⚡ Caching Info"):
        st.markdown("""
        Results cached for **1 hour**. Previously analyzed configs return instantly!

        Free tier has rate limits — wait 30–60s between unique analyses.
        """)

    with st.expander("ℹ️ About XFOIL"):
        st.markdown("""
        **XFOIL** is an industry-standard panel method code developed at MIT.

        Get airfoil files from:
        - [UIUC Database](https://m-selig.ae.illinois.edu/ads/coord_database.html)
        - [Airfoil Tools](http://airfoiltools.com/)
        """)

    with st.expander("📚 Example Airfoils"):
        st.markdown("""
        - **NACA 4412** — Classic cambered
        - **NACA 0012** — Symmetric
        - **Clark Y** — Flat-bottom
        - **S1223** — High-lift low-Re
        - **Eppler 387** — Sailplane
        """)

# ── Main content ─────────────────────────────────────────────────────────────
with right_col:
    st.markdown('<p class="main-header">✈️ Airfoil Analysis</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Powered by XFOIL Panel Method</p>', unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "📁 Upload Airfoil .dat File",
        type="dat",
        help="Upload a file with airfoil x,y coordinates"
    )

    run_analysis = st.button("🚀 Run Analysis", type="primary", disabled=(uploaded_file is None))

    if uploaded_file is not None and run_analysis:
        backend_url = os.getenv("BACKEND_URL", BACKEND_URL)

        if 'analyzing' in st.session_state and st.session_state.analyzing:
            st.warning("⏳ Analysis already in progress. Please wait...")
            st.stop()

        st.session_state.analyzing = True

        try:
            file_content = uploaded_file.getvalue()

            with st.spinner("Computing... (30-60s on free tier, instant if cached)"):
                result = run_xfoil_analysis(
                    file_content=file_content,
                    filename=uploaded_file.name,
                    reynolds=reynolds,
                    alpha=alpha,
                    backend_url=backend_url
                )

            new_count = increment_analysis_count()
            if new_count:
                st.toast(f"✅ Analysis #{new_count:,} completed!", icon="🎉")

            st.session_state.results = result
            st.session_state.last_params = {
                'reynolds': reynolds,
                'alpha': alpha,
                'filename': uploaded_file.name
            }
            st.session_state.analyzing = False
            st.success("✅ Simulation completed successfully!")
            st.rerun()

        except Exception as e:
            st.session_state.analyzing = False
            error_msg = str(e)
            if "Retrying" in error_msg:
                st.warning(f"⏳ {error_msg}")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"❌ Error: {error_msg}")
                if "rate-limited" in error_msg.lower() or "429" in error_msg:
                    st.info("💡 **Tip:** Free tier has rate limits. Wait 60 seconds before trying again.")

    # Display results
    if st.session_state.results is not None:
        result = st.session_state.results
        last_params = st.session_state.last_params

        st.info(f"📊 **{last_params['filename']}** | Re = {last_params['reynolds']:,} | α = {last_params['alpha']}°")

        if "coefficients" in result and result["coefficients"]:
            st.markdown("---")
            st.subheader("📊 Aerodynamic Coefficients")

            coeffs = result["coefficients"]

            if "CL" in coeffs:
                if coeffs["CL"] < -0.1:
                    st.warning("⚠️ **Negative Lift Detected!** The airfoil is generating downforce.")
                elif abs(coeffs["CL"]) < 0.001:
                    st.info("ℹ️ **Near-Zero Lift:** Symmetric airfoil at zero AoA — L/D not meaningful.")
                elif coeffs["CL"] < 0.5 and abs(last_params['alpha']) > 10:
                    st.error("🚨 **Possible Stall Condition!** Low CL at high AoA — flow may be separated.")

            coef_cols = st.columns(3)
            metrics = [("CL", "CL"), ("CD", "CD"), ("L/D", None)]

            for idx, (label, key) in enumerate(metrics):
                with coef_cols[idx]:
                    if key and key in coeffs:
                        st.metric(label, f"{coeffs[key]:.4f}")
                    elif label == "L/D" and "CL" in coeffs and "CD" in coeffs:
                        if abs(coeffs["CL"]) < 0.001 or coeffs["CD"] == 0:
                            st.metric(label, "~0", help="CL ≈ 0, L/D not meaningful")
                        else:
                            ld_ratio = coeffs["CL"] / coeffs["CD"]
                            st.metric(label, f"{ld_ratio:.2f}",
                                      help="Negative L/D = downforce" if ld_ratio < 0 else None)
                    else:
                        st.metric(label, "N/A")

        coords_after = pd.DataFrame(result["coords_after"], columns=["x", "y"])

        st.markdown("---")

        plot_col1, plot_col2 = st.columns(2)

        with plot_col1:
            st.subheader("🛩️ Airfoil Geometry")
            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(
                x=coords_after["x"], y=coords_after["y"],
                mode='lines', name='Airfoil',
                line=dict(color='#667eea', width=3),
                fill='toself', fillcolor='rgba(102, 126, 234, 0.2)',
                hovertemplate='x: %{x:.4f}<br>y: %{y:.4f}<extra></extra>'
            ))
            fig1.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.3)
            fig1.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.3)
            fig1.update_layout(
                title=last_params['filename'],
                xaxis_title="x/c", yaxis_title="y/c",
                height=400, hovermode='closest',
                plot_bgcolor='white',
                yaxis=dict(scaleanchor="x", scaleratio=1)
            )
            fig1.update_xaxes(showgrid=True, gridcolor='lightgray')
            fig1.update_yaxes(showgrid=True, gridcolor='lightgray')
            st.plotly_chart(fig1, use_container_width=True)

            with st.expander("🔍 Geometry Details"):
                st.write(f"**Points:** {len(coords_after)}")
                st.write(f"**Max thickness:** {(coords_after['y'].max() - coords_after['y'].min()):.4f}")
                st.write(f"**Chord length:** {coords_after['x'].max() - coords_after['x'].min():.4f}")

        with plot_col2:
            if result["cp_x"] and result["cp_values"]:
                st.subheader("📈 Pressure Distribution")
                cp_x = np.array(result["cp_x"])
                cp_values = np.array(result["cp_values"])
                fig2 = go.Figure()
                mid_idx = len(cp_x) // 2
                fig2.add_trace(go.Scatter(
                    x=cp_x[:mid_idx], y=cp_values[:mid_idx],
                    mode='lines', name='Upper surface',
                    line=dict(color='#3b82f6', width=3),
                    hovertemplate='x/c: %{x:.4f}<br>Cp: %{y:.4f}<extra></extra>'
                ))
                fig2.add_trace(go.Scatter(
                    x=cp_x[mid_idx:], y=cp_values[mid_idx:],
                    mode='lines', name='Lower surface',
                    line=dict(color='#ef4444', width=3),
                    hovertemplate='x/c: %{x:.4f}<br>Cp: %{y:.4f}<extra></extra>'
                ))
                fig2.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.3)
                fig2.update_layout(
                    title=f"Re = {last_params['reynolds']:,.0f}, α = {last_params['alpha']}°",
                    xaxis_title="x/c", yaxis_title="Cp",
                    height=400, hovermode='closest',
                    plot_bgcolor='white',
                    yaxis=dict(autorange='reversed')
                )
                fig2.update_xaxes(showgrid=True, gridcolor='lightgray')
                fig2.update_yaxes(showgrid=True, gridcolor='lightgray')
                st.plotly_chart(fig2, use_container_width=True)

                with st.expander("📖 Understanding Cp"):
                    st.markdown("""
                    **Pressure Coefficient (Cp):**
                    - Negative Cp = Lower pressure (suction)
                    - Positive Cp = Higher pressure
                    - Upper surface: lower pressure (negative Cp)
                    - Lower surface: higher pressure (positive Cp)
                    - The difference creates lift!
                    """)
            else:
                st.warning("⚠️ No pressure coefficient data available")

        st.markdown("---")
        if st.button("💾 Download Results as CSV"):
            csv_data = pd.DataFrame({'x': result["cp_x"], 'Cp': result["cp_values"]})
            csv = csv_data.to_csv(index=False)
            st.download_button(
                label="Download Cp Data",
                data=csv,
                file_name=f"{last_params['filename'].replace('.dat', '')}_cp_results.csv",
                mime="text/csv"
            )

    elif uploaded_file is not None:
        st.info("⚙️ Parameters set. Click 'Run Analysis' to start simulation.")
    else:
        st.info("👆 Upload an airfoil .dat file to begin analysis")
        st.markdown("---")
        st.markdown("### 🎓 Quick Start Guide")

        guide_col1, guide_col2 = st.columns(2)

        with guide_col1:
            st.markdown("""
            **Step 1: Get an airfoil file**
            - Visit [UIUC Database](https://m-selig.ae.illinois.edu/ads/coord_database.html)
            - Search for an airfoil (e.g., "NACA 4412")
            - Download the .dat file
            """)

        with guide_col2:
            st.markdown("""
            **Step 2: Set parameters**
            - Choose Reynolds number from the left panel
            - Select angle of attack using the slider
            - Upload your .dat file above
            """)