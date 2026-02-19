import streamlit as st

# Page configuration
st.set_page_config(page_title="About - AeroLab", layout="wide", page_icon="✈️",
                   initial_sidebar_state="collapsed")

# Always hide sidebar completely
st.markdown("""
    <style>
        [data-testid="stSidebarNav"]    {display: none;}
        [data-testid="collapsedControl"] {display: none;}
        section[data-testid="stSidebar"] {display: none;}
    </style>
""", unsafe_allow_html=True)

# Back button
if st.button("← Back to Home"):
    st.switch_page("app.py")

# Custom CSS
st.markdown("""
    <style>
    .about-header {
        font-size: 3.5rem;
        font-weight: bold;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 2rem;
    }
    .section-title {
        font-size: 2rem;
        font-weight: bold;
        color: #667eea;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    .content-box {
        background: #f8f9fa;
        padding: 2rem;
        border-radius: 15px;
        margin: 1rem 0;
        border-left: 5px solid #667eea;
        color: #333;
    }
    .content-box h3 {
        color: #667eea;
        margin-bottom: 1rem;
    }
    .content-box p, .content-box ul, .content-box li {
        color: #333;
    }
    .developer-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 20px;
        color: white;
        text-align: center;
        box-shadow: 0 10px 30px rgba(102, 126, 234, 0.3);
    }
    .dev-name {
        font-size: 2rem;
        font-weight: bold;
        margin-top: 1rem;
    }
    .dev-title {
        font-size: 1.2rem;
        opacity: 0.9;
        margin-bottom: 1rem;
    }
    </style>
""", unsafe_allow_html=True)

# Header
st.markdown('<h1 class="about-header">📖 About AeroLab</h1>', unsafe_allow_html=True)

# What is AeroLab
st.markdown('<h2 class="section-title">What is AeroLab?</h2>', unsafe_allow_html=True)
st.markdown("""
<div class="content-box">
<p style="font-size: 1.1rem; line-height: 1.8;">
AeroLab is a professional-grade web application designed to make airfoil aerodynamic analysis accessible to students, 
researchers, and aerospace enthusiasts. Built on the industry-standard <strong>XFOIL panel method solver</strong>, 
AeroLab provides accurate predictions of lift, drag, and pressure distributions for 2D airfoil sections.
</p>
<p style="font-size: 1.1rem; line-height: 1.8;">
Whether you're designing a model aircraft, studying aerospace engineering, or exploring computational fluid dynamics, 
AeroLab offers a user-friendly interface to perform complex aerodynamic calculations without requiring expensive 
software licenses or high-performance computing resources.
</p>
</div>
""", unsafe_allow_html=True)

# Key Features
st.markdown('<h2 class="section-title">⚡ Key Features</h2>', unsafe_allow_html=True)

feature_col1, feature_col2 = st.columns(2)

with feature_col1:
    st.markdown("""
    <div class="content-box">
    <h3>🎯 Accurate Predictions</h3>
    <p>Powered by XFOIL, the most widely-used and validated panel method code in aerospace engineering. 
    Trusted by universities and industry worldwide.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="content-box">
    <h3>📊 Visual Analytics</h3>
    <p>Interactive plots showing airfoil geometry, pressure distributions, and aerodynamic coefficients. 
    Understand the physics through visualization.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="content-box">
    <h3>🌐 Cloud-Based</h3>
    <p>No installation required. Access from any device with a web browser. 
    Results are cached for instant retrieval.</p>
    </div>
    """, unsafe_allow_html=True)

with feature_col2:
    st.markdown("""
    <div class="content-box">
    <h3>⚙️ Flexible Configuration</h3>
    <p>Analyze airfoils across a wide range of Reynolds numbers (10,000 to 10,000,000) and 
    angles of attack (-10° to +20°).</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="content-box">
    <h3>💾 Export Results</h3>
    <p>Download pressure distribution data as CSV files for further analysis, 
    reporting, or integration with other tools.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="content-box">
    <h3>📚 Educational</h3>
    <p>Perfect for learning aerodynamics, validating designs, or conducting research. 
    Supports standard airfoil coordinate formats.</p>
    </div>
    """, unsafe_allow_html=True)

# Technical Details
st.markdown('<h2 class="section-title">🔬 Technical Details</h2>', unsafe_allow_html=True)
st.markdown("""
<div class="content-box">
<h3>XFOIL Panel Method</h3>
<p style="font-size: 1.05rem; line-height: 1.8;">
XFOIL is a design and analysis system for low Reynolds number subsonic isolated airfoils, 
developed by Professor Mark Drela at MIT. It combines:
</p>
<ul style="font-size: 1.05rem; line-height: 1.8;">
    <li><strong>Panel Method:</strong> Inviscid flow solution using source and vortex panels</li>
    <li><strong>Boundary Layer Analysis:</strong> Viscous effects through integral boundary layer formulation</li>
    <li><strong>Transition Prediction:</strong> Natural and forced transition modeling</li>
    <li><strong>Wake Modeling:</strong> Accurate drag prediction through wake panel representation</li>
</ul>

<h3>Platform Architecture</h3>
<ul style="font-size: 1.05rem; line-height: 1.8;">
    <li><strong>Frontend:</strong> Streamlit (Python) for interactive web interface</li>
    <li><strong>Backend:</strong> FastAPI with XFOIL integration</li>
    <li><strong>Deployment:</strong> Streamlit Community Cloud (frontend) + Render (backend)</li>
    <li><strong>Caching:</strong> Smart result caching for improved performance</li>
</ul>
</div>
""", unsafe_allow_html=True)

# Developer Section
st.markdown('<h2 class="section-title">👨‍💻 Developer</h2>', unsafe_allow_html=True)

dev_col1, dev_col2, dev_col3 = st.columns([1, 2, 1])

with dev_col2:
    col_img1, col_img2, col_img3 = st.columns([1, 2, 1])
    with col_img2:
        try:
            st.image("developer.jpg", use_container_width=True)
        except:
            st.markdown('<div style="text-align: center; font-size: 5rem; margin-bottom: 1rem;">👤</div>', unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown("""
    <div class="developer-card">
        <div class="dev-name">Nathan Pranav</div>
        <div class="dev-title">Aspiring Aerospace Engineer</div>
        <hr style="border-color: rgba(255,255,255,0.3); margin: 1.5rem 0;">
        <p style="font-size: 1.05rem; line-height: 1.8; text-align: center; opacity: 0.95;">
        Passionate about computational fluid dynamics and aerospace design. 
        AeroLab was developed to make professional-grade aerodynamic analysis tools 
        accessible to students and educators worldwide.
        </p>
        <p style="font-size: 1.05rem; margin-top: 1rem; text-align: center;">
        <strong>Interests:</strong><br>
        Aerodynamics • CFD • CAD • Research
        </p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# How to Use
st.markdown('<h2 class="section-title">📖 How to Use AeroLab</h2>', unsafe_allow_html=True)

step_col1, step_col2, step_col3, step_col4 = st.columns(4)

with step_col1:
    st.markdown("""
    <div class="content-box" style="text-align: center;">
    <div style="font-size: 3rem;">🔍</div>
    <h4>1. Get Airfoil Data</h4>
    <p>Download .dat coordinate files from UIUC Airfoil Database or Airfoil Tools</p>
    </div>
    """, unsafe_allow_html=True)

with step_col2:
    st.markdown("""
    <div class="content-box" style="text-align: center;">
    <div style="font-size: 3rem;">⚙️</div>
    <h4>2. Set Parameters</h4>
    <p>Choose Reynolds number and angle of attack for your analysis</p>
    </div>
    """, unsafe_allow_html=True)

with step_col3:
    st.markdown("""
    <div class="content-box" style="text-align: center;">
    <div style="font-size: 3rem;">🚀</div>
    <h4>3. Run Analysis</h4>
    <p>Click analyze and wait 30-60 seconds for XFOIL to compute results</p>
    </div>
    """, unsafe_allow_html=True)

with step_col4:
    st.markdown("""
    <div class="content-box" style="text-align: center;">
    <div style="font-size: 3rem;">📊</div>
    <h4>4. View Results</h4>
    <p>Explore coefficients, pressure plots, and download data</p>
    </div>
    """, unsafe_allow_html=True)

# Contact & Support
st.markdown('<h2 class="section-title">💬 Contact & Support</h2>', unsafe_allow_html=True)
st.markdown("""
<div class="content-box">
<p style="font-size: 1.05rem;">
For questions, suggestions, or collaboration opportunities, please reach out through GitHub or email.
This is an open educational project aimed at advancing aerospace education.
</p>
<p style="font-size: 1.05rem; margin-top: 1rem;">
<strong>Note:</strong> This tool is provided for educational purposes. For critical applications, 
always validate results with experimental data or higher-fidelity CFD methods.
</p>
</div>
""", unsafe_allow_html=True)

# Footer
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown("""
    <div style="text-align: center; color: #999; padding: 2rem;">
        <p>AeroLab © 2026 • Built with Streamlit & XFOIL</p>
        <p style="font-size: 0.9rem;">Advancing Aerospace Education, One Airfoil at a Time</p>
    </div>
""", unsafe_allow_html=True)