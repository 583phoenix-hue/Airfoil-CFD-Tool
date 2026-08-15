import streamlit as st
import requests
import os
from db_utils import init_db, get_analysis_count
from aerolab_theme import COLORS, CMAP_GRADIENT, inject_theme, cmap_bar

# Page configuration
st.set_page_config(
    page_title="AeroLab - Airfoil Analysis Tool",
    layout="wide",
    page_icon="✈️",
    initial_sidebar_state="collapsed"
)

inject_theme()

# Initialize database on app startup
init_db()

# ── Backend Health Check ────────────────────────────────────────────────────
BACKEND_URL = "https://aerolab-backend.onrender.com"
IS_LOCAL = os.environ.get("LOCAL_DEV", "false").lower() == "true"

@st.cache_data(ttl=30, show_spinner=False)
def check_backend() -> str:
    """
    Returns one of three states:
      "online"    — backend responded and is healthy
      "suspended" — Render monthly limit page detected
      "offline"   — timeout, connection error, or unexpected response
    """
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=8)
        if "suspended" in response.text.lower() or "service has been suspended" in response.text.lower():
            return "suspended"
        if response.status_code == 200:
            return "online"
        return "offline"
    except requests.exceptions.Timeout:
        return "offline"
    except Exception:
        return "offline"

# Bypass health check entirely when running locally
backend_status = "online" if IS_LOCAL else check_backend()

# Show popup once per session if backend is suspended
if backend_status == "suspended" and not st.session_state.get("suspension_popup_shown"):
    @st.dialog("🛠️ Solver Temporarily Unavailable")
    def suspension_popup():
        st.warning("**Scheduled Maintenance Underway**")
        st.markdown(
            "The aerodynamic solver is undergoing scheduled maintenance. "
            "Please check again shortly.\n\n"
            "You can still browse the site — analysis functionality will return shortly!"
        )
        if st.button("Got it", use_container_width=True, type="primary"):
            st.session_state["suspension_popup_shown"] = True
            st.rerun()
    suspension_popup()
# ───────────────────────────────────────────────────────────────────────────

# ── Nav ──────────────────────────────────────────────────────────────────
st.markdown(f"""
    <div style="display:flex; align-items:center; gap:10px; font-family:'Space Grotesk',sans-serif;
                font-weight:600; font-size:17px; padding-top:0.5rem;">
        <span style="width:26px; height:26px; border-radius:6px; display:flex; align-items:center;
                     justify-content:center; font-size:13px;
                     background:linear-gradient(135deg, {COLORS['c1']}, {COLORS['c3']}, {COLORS['c6']});">✈</span>
        <span>AeroLab</span>
    </div>
""", unsafe_allow_html=True)
cmap_bar()

# ── Hero ─────────────────────────────────────────────────────────────────
_, hero_col, _ = st.columns([1, 4, 1])
with hero_col:
    st.markdown(f"""
        <div style="width:100%; text-align:center;">
        <h1 style="font-size:clamp(32px,5vw,52px); line-height:1.1; text-align:center; margin:20px 0 4px;">
            Welcome to <span style="background:{CMAP_GRADIENT}; -webkit-background-clip:text; background-clip:text;
                     color:transparent; -webkit-text-fill-color:transparent;">AeroLab</span>
        </h1>
        <p style="text-align:center; font-size:16px; color:{COLORS['text_dim']}; max-width:520px; margin:0 auto 32px;">
            Upload a .dat, get lift, drag, and pressure distribution back in seconds — powered by XFOIL,
            with a parser built to handle real-world UIUC coordinate file quirks automatically.
        </p>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Call-to-Action Buttons ──────────────────────────────────────────────────
col1, col2, col3 = st.columns([1, 1, 1])

with col2:
    if backend_status == "online":
        if st.button("🚀 Analyze airfoil", key="analyze", use_container_width=True, type="primary"):
            st.switch_page("pages/Airfoil_Analysis.py")

    elif backend_status == "suspended":
        st.error("🛠️ Maintenance ongoing")
        st.info("Wind tunnel undergoing maintenance for a better experience. Check back soon!")
        st.button("Analyze airfoil (offline)", key="analyze_suspended", use_container_width=True, disabled=True)

    else:
        st.warning("⏳ Solver waking up…")
        st.info(
            "The aerodynamic solver is starting up due to inactivity (Render free tier, ~30–60s). "
            "Please wait and refresh."
        )
        st.button("Analyze airfoil (starting…)", key="analyze_offline", use_container_width=True, disabled=True)

    if st.button("📖 About AeroLab", key="about", use_container_width=True):
        st.switch_page("pages/About.py")

st.markdown("<br>", unsafe_allow_html=True)

# ── Analysis Counter ─────────────────────────────────────────────────────
analysis_count = get_analysis_count()

_, counter_col, _ = st.columns([1, 2, 1])
with counter_col:
    count_display = f"{analysis_count:,}" if analysis_count is not None else "—"
    count_desc = "Airfoils analyzed by aerospace enthusiasts worldwide" if analysis_count is not None else "Database initializing…"
    st.markdown(f"""
        <div class="card" style="text-align:center;">
            <div style="font-size:12.5px; color:{COLORS['text_faint']}; text-transform:uppercase;
                        letter-spacing:0.06em; margin-bottom:6px;">Total analyses performed</div>
            <div class="mono" style="font-size:36px; font-weight:500;">{count_display}</div>
            <div style="font-size:12px; color:{COLORS['text_faint']}; margin-top:4px;">{count_desc}</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)

# ── Features Section ─────────────────────────────────────────────────────
st.markdown("<h2 style='margin-top:12px;'>Features</h2>", unsafe_allow_html=True)

feature_col1, feature_col2, feature_col3 = st.columns(3)
features = [
    ("🎯", "Accurate analysis", "Industry-standard XFOIL panel method for precise aerodynamic predictions.", COLORS["c2"]),
    ("⚡", "Fast results", "Robust coordinate parsing means fewer failed runs and less waiting.", COLORS["c3"]),
    ("📊", "Visual insights", "Interactive pressure distribution, geometry, and wind tunnel visualization.", COLORS["c5"]),
]
for col, (icon, title, desc, accent) in zip([feature_col1, feature_col2, feature_col3], features):
    with col:
        st.markdown(f"""
            <div class="card" style="height:100%;">
                <div style="width:36px; height:36px; border-radius:8px; display:flex; align-items:center;
                            justify-content:center; margin-bottom:16px; font-size:16px;
                            background:{accent}20; color:{accent};">{icon}</div>
                <div style="font-size:16px; font-weight:500; color:{COLORS['text']}; margin-bottom:8px;
                            font-family:'Inter',sans-serif;">{title}</div>
                <div style="font-size:14px; color:{COLORS['text_dim']}; line-height:1.6;">{desc}</div>
            </div>
        """, unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)

# ── How It Works ──────────────────────────────────────────────────────────
st.markdown("<h2 style='margin-top:12px;'>How it works</h2>", unsafe_allow_html=True)

step_col1, step_col2, step_col3 = st.columns(3)
steps = [
    ("01", "Upload", "Airfoil coordinate file (.dat/.txt) from UIUC or Airfoil Tools, or pick a bundled example."),
    ("02", "Configure", "Set Reynolds number, angle of attack, NCrit, and viscous/inviscid mode."),
    ("03", "Analyze", "Get lift, drag, moment coefficients, and detailed pressure distributions."),
]
for col, (n, title, desc) in zip([step_col1, step_col2, step_col3], steps):
    with col:
        st.markdown(f"""
            <div class="card" style="height:100%;">
                <div class="mono" style="font-size:11px; color:{COLORS['text_faint']}; margin-bottom:8px;">{n}</div>
                <div style="font-size:15px; font-weight:500; color:{COLORS['text']}; margin-bottom:6px;">{title}</div>
                <div style="font-size:13px; color:{COLORS['text_dim']};">{desc}</div>
            </div>
        """, unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────
st.markdown("<br><br>", unsafe_allow_html=True)
cmap_bar()
st.markdown(f"""
    <div style="text-align:center; color:{COLORS['text_faint']}; font-family:'JetBrains Mono',monospace;
                font-size:12px; padding-bottom:2rem;">
        Powered by XFOIL · For educational use · AeroLab © 2026
    </div>
""", unsafe_allow_html=True)