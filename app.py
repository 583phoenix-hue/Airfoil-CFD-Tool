import streamlit as st
import requests
from db_utils import init_db, get_analysis_count

# Page configuration
st.set_page_config(
    page_title="AeroLab - Airfoil Analysis Tool", 
    layout="wide", 
    page_icon="✈️",
    initial_sidebar_state="collapsed"
)

# Always hide sidebar completely across all pages
st.markdown("""
    <style>
        [data-testid="stSidebarNav"]    {display: none;}
        [data-testid="collapsedControl"] {display: none;}
        section[data-testid="stSidebar"] {display: none;}
    </style>
""", unsafe_allow_html=True)

# Initialize database on app startup
init_db()

# ── Backend Health Check ────────────────────────────────────────────────────
BACKEND_URL = "https://aerolab-backend.onrender.com"


@st.cache_data(ttl=30)  # Re-check at most once per half-minute
def check_backend() -> str:
    """
    Returns one of three states:
      "online"    — backend responded and is healthy
      "suspended" — Render's monthly limit page detected
      "offline"   — timeout, connection error, or unexpected response
    """
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=8)
        # Render serves a plain-text/HTML suspension notice with status 200
        # We detect it by looking for the suspension message in the body
        if "suspended" in response.text.lower() or "service has been suspended" in response.text.lower():
            return "suspended"
        if response.status_code == 200:
            return "online"
        return "offline"
    except requests.exceptions.Timeout:
        # Cold start timeout — don't penalise users, treat as offline for now
        return "offline"
    except Exception:
        return "offline"

backend_status = check_backend()

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

# Custom CSS
st.markdown("""
    <style>
    .hero-title {
        font-size: 4.5rem;
        font-weight: bold;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-top: 3rem;
        margin-bottom: 1rem;
    }
    .hero-subtitle {
        font-size: 1.5rem;
        text-align: center;
        color: #666;
        margin-bottom: 3rem;
        line-height: 1.6;
    }
    .feature-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        color: white;
        text-align: center;
        margin: 1rem 0;
        box-shadow: 0 10px 30px rgba(102, 126, 234, 0.3);
    }
    .feature-icon {
        font-size: 3rem;
        margin-bottom: 1rem;
    }
    .feature-title {
        font-size: 1.5rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    .feature-desc {
        font-size: 1rem;
        opacity: 0.9;
    }
    .footer {
        text-align: center;
        color: #999;
        margin-top: 5rem;
        padding: 2rem;
    }
    .visitor-counter {
        text-align: center;
        margin: 2rem 0;
        padding: 2rem;
        background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
        border-radius: 20px;
        border: 2px solid #667eea30;
    }
    .counter-label {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 0.5rem;
        font-weight: 500;
    }
    .counter-number {
        font-size: 3.5rem;
        font-weight: bold;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0.5rem 0;
    }
    .counter-description {
        font-size: 0.9rem;
        color: #999;
        margin-top: 0.5rem;
    }
    </style>
""", unsafe_allow_html=True)

# Hero Section
st.markdown('<h1 class="hero-title">✈️ Welcome to AeroLab</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-subtitle">Professional-grade airfoil aerodynamic analysis powered by XFOIL<br>'
    'Analyze lift, drag, pressure distribution, and performance characteristics in seconds</p>',
    unsafe_allow_html=True
)

st.markdown("<br>", unsafe_allow_html=True)

# ── Call-to-Action Buttons ──────────────────────────────────────────────────
col1, col2, col3 = st.columns([1, 1, 1])

with col2:
    if backend_status == "online":
        # ✅ Backend healthy — full functionality
        if st.button("🚀 Analyze Airfoil", key="analyze", use_container_width=True, type="primary"):
            st.switch_page("pages/Airfoil_Analysis.py")

    elif backend_status == "suspended":
        # 🛠️ Render monthly limit hit — show clear maintenance notice
        st.error("🛠️ Maintenance Ongoing")
        st.info(
            "Wind tunnel undergoing maintenance for a better experience. "
            "Check back soon!"
        )
        st.button("🚀 Analyze Airfoil (Offline)", key="analyze_suspended", use_container_width=True, disabled=True)

    else:
        # 🔴 Offline / cold starting — softer message since it may just be waking up
        st.warning("⏳ Solver Waking Up...")
        st.info(
            "The aerodynamic solver is currently starting up. "
            "Please wait ~30 seconds and refresh the page."
        )
        st.button("🚀 Analyze Airfoil (Starting...)", key="analyze_offline", use_container_width=True, disabled=True)

    if st.button("📖 About AeroLab", key="about", use_container_width=True):
        st.switch_page("pages/About.py")

# ───────────────────────────────────────────────────────────────────────────

st.markdown("<br><br>", unsafe_allow_html=True)

# Analysis Counter - Using PostgreSQL Database
analysis_count = get_analysis_count()

if analysis_count is not None:
    st.markdown(f"""
        <div class="visitor-counter">
            <div class="counter-label">🔬 Total Analyses Performed</div>
            <div class="counter-number">{analysis_count:,}</div>
            <div class="counter-description">Airfoils analyzed by aerospace enthusiasts worldwide</div>
        </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
        <div class="visitor-counter">
            <div class="counter-label">🔬 Analysis Counter</div>
            <div class="counter-description">Database initializing...</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Features Section
st.markdown("### ⚡ Features")

feature_col1, feature_col2, feature_col3 = st.columns(3)

with feature_col1:
    st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">🎯</div>
            <div class="feature-title">Accurate Analysis</div>
            <div class="feature-desc">Industry-standard XFOIL panel method for precise aerodynamic predictions</div>
        </div>
    """, unsafe_allow_html=True)

with feature_col2:
    st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">⚡</div>
            <div class="feature-title">Fast Results</div>
            <div class="feature-desc">Smart caching delivers instant results for previously analyzed configurations</div>
        </div>
    """, unsafe_allow_html=True)

with feature_col3:
    st.markdown("""
        <div class="feature-card">
            <div class="feature-icon">📊</div>
            <div class="feature-title">Visual Insights</div>
            <div class="feature-desc">Interactive pressure distribution and geometry plots for deep understanding</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)

# How It Works
st.markdown("### 🛠️ How It Works")

step_col1, step_col2, step_col3 = st.columns(3)

with step_col1:
    st.markdown("#### 1️⃣ Upload")
    st.markdown("Upload your airfoil coordinate file (.dat format) from databases like UIUC or Airfoil Tools")

with step_col2:
    st.markdown("#### 2️⃣ Configure")
    st.markdown("Set Reynolds number and angle of attack for your flight conditions")

with step_col3:
    st.markdown("#### 3️⃣ Analyze")
    st.markdown("Get lift, drag, moment coefficients, and detailed pressure distributions")

# Footer
st.markdown("""
    <div class="footer">
        <p>Built with Streamlit • Powered by XFOIL • For Educational Use</p>
        <p style="font-size: 0.9rem;">AeroLab © 2026 • Advancing Aerospace Education</p>
    </div>
""", unsafe_allow_html=True)