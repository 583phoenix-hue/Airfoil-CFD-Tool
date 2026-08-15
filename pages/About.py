import streamlit as st
from aerolab_theme import COLORS, inject_theme, cmap_bar, eyebrow

st.set_page_config(page_title="About - AeroLab", layout="wide", page_icon="✈️",
                   initial_sidebar_state="collapsed")

inject_theme()

if st.button("← Back to home"):
    st.switch_page("app.py")

st.markdown("<br>", unsafe_allow_html=True)
eyebrow("The project")
st.markdown("<h1 style='margin-top:16px;'>About AeroLab</h1>", unsafe_allow_html=True)
cmap_bar()


def section_title(text):
    st.markdown(f"<h2 style='font-size:20px; margin-top:32px; margin-bottom:16px;'>{text}</h2>", unsafe_allow_html=True)


def content_box(html):
    st.markdown(f'<div class="card" style="height:100%;">{html}</div>', unsafe_allow_html=True)


# ── What is AeroLab ──────────────────────────────────────────────────────
section_title("What is AeroLab?")
content_box(f"""
    <p style="font-size:15px; line-height:1.7; color:{COLORS['text_dim']}; margin-bottom:12px;">
    AeroLab is a web application designed to make airfoil aerodynamic analysis accessible to students,
    researchers, and aerospace enthusiasts. Built on the industry-standard XFOIL panel method solver,
    it predicts lift, drag, and pressure distributions for 2D airfoil sections.
    </p>
    <p style="font-size:15px; line-height:1.7; color:{COLORS['text_dim']};">
    Whether you're designing a model aircraft, studying aerospace engineering, or exploring computational
    fluid dynamics, AeroLab offers a way to run aerodynamic calculations without expensive software or
    high-performance computing.
    </p>
""")

# ── Key Features ─────────────────────────────────────────────────────────
section_title("Key features")

feature_col1, feature_col2 = st.columns(2)
features_left = [
    ("🎯", "Accurate predictions", "Powered by XFOIL, the most widely-used and validated panel method code in aerospace engineering."),
    ("📊", "Visual analytics", "Airfoil geometry, pressure distributions, boundary layer data, and an interactive wind tunnel."),
    ("🌐", "Cloud-based", "No installation required. Access from any device with a web browser."),
]
features_right = [
    ("⚙️", "Flexible configuration", "Reynolds numbers from 10,000 to 10,000,000 and angles of attack from -20° to +25°."),
    ("💾", "Export results", "Download pressure distribution and boundary-layer data as CSV for further analysis."),
    ("⚖️", "Compare mode", "Two airfoils side by side, with a shared interactive wind tunnel."),
]

with feature_col1:
    for icon, title, desc in features_left:
        content_box(f"""
            <div style="font-size:20px; margin-bottom:8px;">{icon}</div>
            <div style="font-size:14px; font-weight:500; color:{COLORS['text']}; margin-bottom:6px;">{title}</div>
            <div style="font-size:13px; color:{COLORS['text_dim']}; line-height:1.6;">{desc}</div>
        """)
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

with feature_col2:
    for icon, title, desc in features_right:
        content_box(f"""
            <div style="font-size:20px; margin-bottom:8px;">{icon}</div>
            <div style="font-size:14px; font-weight:500; color:{COLORS['text']}; margin-bottom:6px;">{title}</div>
            <div style="font-size:13px; color:{COLORS['text_dim']}; line-height:1.6;">{desc}</div>
        """)
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

# ── Technical Details ────────────────────────────────────────────────────
section_title("Technical details")
content_box(f"""
    <h3 style="font-size:15px; font-weight:500; color:{COLORS['text']}; margin-bottom:10px;">XFOIL panel method</h3>
    <p style="font-size:14px; color:{COLORS['text_dim']}; margin-bottom:14px; line-height:1.7;">
    XFOIL is a design and analysis system for low Reynolds number subsonic isolated airfoils, developed by
    Professor Mark Drela at MIT. It combines:
    </p>
    <ul style="font-size:14px; color:{COLORS['text_dim']}; line-height:1.8; padding-left:20px; margin-bottom:18px;">
        <li><strong style="color:{COLORS['text']};">Panel method</strong> — inviscid flow solution using source and vortex panels</li>
        <li><strong style="color:{COLORS['text']};">Boundary layer analysis</strong> — viscous effects via integral formulation, with adjustable NCrit</li>
        <li><strong style="color:{COLORS['text']};">Transition prediction</strong> — natural transition modeling (e^N method)</li>
        <li><strong style="color:{COLORS['text']};">Wake modeling</strong> — accurate drag prediction through wake panel representation</li>
    </ul>
    <h3 style="font-size:15px; font-weight:500; color:{COLORS['text']}; margin-bottom:10px;">Platform architecture</h3>
    <ul style="font-size:14px; color:{COLORS['text_dim']}; line-height:1.8; padding-left:20px;">
        <li><strong style="color:{COLORS['text']};">Frontend</strong> — Streamlit (Python)</li>
        <li><strong style="color:{COLORS['text']};">Backend</strong> — FastAPI with XFOIL subprocess integration</li>
        <li><strong style="color:{COLORS['text']};">Coordinate parser</strong> — auto-repairs Lednicer/Selig format issues, winding order, duplicate points</li>
    </ul>
""")

# ── Developer ─────────────────────────────────────────────────────────────
section_title("Developer")
 
import os as _os
 
_, dev_col, _ = st.columns([1, 1.5, 1])
with dev_col:
    _, img_col, _ = st.columns([1, 1.4, 1])
    with img_col:
        _here = _os.path.dirname(_os.path.abspath(__file__))
        _parent = _os.path.dirname(_here)
        _search_dirs = [_here, _parent, _os.getcwd()]
        _names = ["developer.jpg", "developer.jpeg", "developer.png",
                  "Developer.jpg", "Developer.JPG", "developer.JPG"]
        _found = None
        for _d in _search_dirs:
            for _name in _names:
                _path = _os.path.join(_d, _name)
                if _os.path.exists(_path):
                    _found = _path
                    break
            if _found:
                break
        if _found:
            st.image(_found, use_container_width=True)
        else:
            st.markdown('<div style="text-align:center;font-size:40px;margin-bottom:12px;">👤</div>', unsafe_allow_html=True)
            st.caption(f"⚠️ No developer photo found. Searched: {', '.join(_search_dirs)} — expected `developer.jpg` (or .jpeg/.png).")
 
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
 
    st.markdown(f"""
        <div class="card" style="text-align:center;">
            <div style="font-family:'Space Grotesk',sans-serif; font-size:20px; font-weight:600;
                        color:{COLORS['text']}; margin-bottom:4px;">Pranav Nathan</div>
            <div style="font-size:13px; color:{COLORS['text_dim']}; margin-bottom:16px;">Aspiring aerospace engineer</div>
            <p style="font-size:14px; color:{COLORS['text_dim']}; line-height:1.7; max-width:420px; margin:0 auto 12px;">
            Passionate about computational fluid dynamics and aerospace design. AeroLab was built to make
            aerodynamic analysis tools accessible to students and educators worldwide.
            </p>
            <p style="font-size:13px; color:{COLORS['text_faint']};">Aerodynamics · CFD · CAD · Research</p>
        </div>
    """, unsafe_allow_html=True)

# ── How to Use ────────────────────────────────────────────────────────────
section_title("How to use AeroLab")

step_col1, step_col2, step_col3, step_col4 = st.columns(4)
steps = [
    ("🔍", "1. Get airfoil data", "Download .dat files from UIUC or Airfoil Tools, or pick a bundled example."),
    ("⚙️", "2. Set parameters", "Choose Reynolds number, angle of attack, NCrit, and viscous/inviscid mode."),
    ("🚀", "3. Run analysis", "XFOIL runs server-side and returns results, typically in seconds."),
    ("📊", "4. View results", "Coefficients, pressure plots, wind tunnel visualization, and CSV export."),
]
for col, (icon, title, desc) in zip([step_col1, step_col2, step_col3, step_col4], steps):
    with col:
        content_box(f"""
            <div style="text-align:center;">
                <div style="font-size:28px; margin-bottom:10px;">{icon}</div>
                <div style="font-size:13px; font-weight:500; color:{COLORS['text']}; margin-bottom:6px;">{title}</div>
                <div style="font-size:12px; color:{COLORS['text_dim']}; line-height:1.6;">{desc}</div>
            </div>
        """)

# ── Contact & Support ────────────────────────────────────────────────────
section_title("Contact & support")
content_box(f"""
    <p style="font-size:14px; color:{COLORS['text_dim']}; line-height:1.7; margin-bottom:10px;">
    For questions, suggestions, or collaboration opportunities, please reach out through email at <a href="mailto:pranav09nathan@gmail.com" style="color:{COLORS['c2']};">pranav09nathan@gmail.com</a>.
    This is an open educational project aimed at advancing aerospace education.
    </p>
    <p style="font-size:14px; color:{COLORS['text_dim']}; line-height:1.7;">
    <strong style="color:{COLORS['text']};">Note:</strong> this tool is provided for educational purposes.
    For critical applications, always validate results with experimental data or higher-fidelity CFD methods.
    </p>
""")

# ── Footer ────────────────────────────────────────────────────────────────
st.markdown("<br><br>", unsafe_allow_html=True)
cmap_bar()
st.markdown(f"""
    <div style="text-align:center; color:{COLORS['text_faint']}; font-family:'JetBrains Mono',monospace;
                font-size:12px; padding-bottom:2rem;">
        AeroLab © 2026 · Built with XFOIL · Advancing aerospace education, one airfoil at a time
    </div>
""", unsafe_allow_html=True)