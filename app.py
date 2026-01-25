import streamlit as st
import streamlit.components.v1 as components
import time

# Page configuration
st.set_page_config(
    page_title="AeroLab - Airfoil Analysis Tool", 
    layout="wide", 
    page_icon="✈️",
    initial_sidebar_state="collapsed"
)

# GoatCounter tracking - Load this first (outside iframe sandbox)
components.html(
    """
    <script data-goatcounter="https://phoenix583.goatcounter.com/count"
            async src="//gc.zgo.at/count.js"></script>
    """,
    height=0,
)

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

# Spacer
st.markdown("<br>", unsafe_allow_html=True)

# Call-to-Action Buttons
col1, col2, col3 = st.columns([1, 1, 1])

with col2:
    if st.button("🚀 Analyze Airfoil", key="analyze", use_container_width=True, type="primary"):
        st.switch_page("pages/Airfoil_Analysis.py")
    
    if st.button("📖 About AeroLab", key="about", use_container_width=True):
        st.switch_page("pages/About.py")

st.markdown("<br><br>", unsafe_allow_html=True)

# Visitor Counter - Using GoatCounter's SVG badge (CORS-free, reliable)
st.markdown(f"""
    <div class="visitor-counter">
        <div class="counter-label">👥 Total Visitors</div>
        <div style="display: flex; justify-content: center; margin: 1rem 0;">
            <img src="https://phoenix583.goatcounter.com/counter//total.svg?nocache={int(time.time())}" 
                 style="height: 70px; filter: invert(47%) sepia(87%) saturate(345%) hue-rotate(190deg) brightness(95%) contrast(92%);" 
                 alt="Visitor Count">
        </div>
        <div class="counter-description">Aerospace enthusiasts analyzing airfoils worldwide</div>
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

# Footer (GoatCounter tracking already loaded at top)
st.markdown("""
    <div class="footer">
        <p>Built with Streamlit • Powered by XFOIL • For Educational Use</p>
        <p style="font-size: 0.9rem;">AeroLab © 2026 • Advancing Aerospace Education</p>
    </div>
""", unsafe_allow_html=True)