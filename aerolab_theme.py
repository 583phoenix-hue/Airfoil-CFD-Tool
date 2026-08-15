import streamlit as st

COLORS = {
    "bg": "#0a0d14", "bg_raised": "#111623", "bg_card": "#141a29",
    "border": "#212a3d", "border_strong": "#2c3855",
    "text": "#eef1f7", "text_dim": "#9aa4b8", "text_faint": "#5c6683",
    "c1": "#0000ff", "c2": "#00ffff", "c3": "#00ff00",
    "c4": "#ffff00", "c5": "#ff8000", "c6": "#ff0000",
}

CMAP_GRADIENT = f"linear-gradient(90deg, {COLORS['c1']}, {COLORS['c2']}, {COLORS['c3']}, {COLORS['c4']}, {COLORS['c5']}, {COLORS['c6']})"


def inject_theme(hide_sidebar: bool = True):
    """Applies the dark AeroLab theme (base styles, fonts, hidden chrome)."""
    hide_chrome_css = """
        [data-testid="stSidebarNav"]    {display: none;}
        [data-testid="collapsedControl"] {display: none;}
        section[data-testid="stSidebar"] {display: none;}
        footer {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        header, [data-testid="stHeader"] {
            visibility: hidden !important;
            height: 0 !important;
            min-height: 0 !important;
        }
        div[data-testid="stToolbar"]    {visibility: hidden; height: 0%;}
        div[data-testid="stDecoration"] {visibility: hidden; height: 0%;}
    """ if hide_sidebar else ""

    st.markdown(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

        {hide_chrome_css}

        html, body, [class*="css"] {{
            font-family: 'Inter', sans-serif;
        }}
        [data-testid="stAppViewContainer"], [data-testid="stApp"] {{
            background-color: {COLORS['bg']};
            color: {COLORS['text']};
        }}
        [data-testid="stAppViewContainer"] > .main,
        [data-testid="stMain"] {{
            padding-top: 0 !important;
        }}
        [data-testid="stAppViewContainer"] .main .block-container,
        [data-testid="stMainBlockContainer"],
        .block-container {{
            max-width: 1300px !important;
            padding-top: 1.5rem !important;
            margin-top: 0 !important;
        }}
        h1, h2, h3, h4 {{
            font-family: 'Space Grotesk', sans-serif !important;
            font-weight: 600 !important;
            color: {COLORS['text']} !important;
        }}
        p, span, div, label {{
            color: {COLORS['text_dim']};
        }}
        .cmap-bar {{
            height: 3px; width: 100%; margin: 0.5rem 0 1.5rem;
            background: {CMAP_GRADIENT};
            border-radius: 2px;
        }}
        .mono {{ font-family: 'JetBrains Mono', monospace; }}
        .eyebrow {{
            display: inline-flex; align-items: center; gap: 8px; font-size: 12px;
            color: {COLORS['text_dim']}; font-family: 'JetBrains Mono', monospace;
            letter-spacing: 0.04em; padding: 6px 12px;
            border: 1px solid {COLORS['border_strong']}; border-radius: 20px;
        }}
        .card {{
            background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']};
            border-radius: 10px; padding: 20px 22px;
        }}

        /* Buttons */
        .stButton > button {{
            background-color: {COLORS['text']} !important;
            border: 1px solid transparent !important;
            border-radius: 8px !important;
            font-weight: 500 !important;
            font-family: 'Inter', sans-serif !important;
            opacity: 1 !important;
        }}
        .stButton > button, .stButton > button p, .stButton > button div, .stButton > button span {{
            color: {COLORS['bg']} !important;
            -webkit-text-fill-color: {COLORS['bg']} !important;
        }}
        .stButton > button:hover {{
            background-color: #d5dae4 !important;
        }}
        .stButton > button:hover, .stButton > button:hover p, .stButton > button:hover div, .stButton > button:hover span {{
            color: {COLORS['bg']} !important;
            -webkit-text-fill-color: {COLORS['bg']} !important;
        }}
        .stButton > button:disabled, .stButton > button:disabled p, .stButton > button:disabled div, .stButton > button:disabled span {{
            background-color: {COLORS['border_strong']} !important;
            color: {COLORS['text_faint']} !important;
            -webkit-text-fill-color: {COLORS['text_faint']} !important;
        }}

        /* Alerts (info/warning/error) — restyle to match dark theme */
        [data-testid="stAlert"] {{
            background-color: {COLORS['bg_card']} !important;
            border: 1px solid {COLORS['border']} !important;
            color: {COLORS['text_dim']} !important;
            border-radius: 8px !important;
        }}
        </style>
    """, unsafe_allow_html=True)


def cmap_bar():
    st.markdown('<div class="cmap-bar"></div>', unsafe_allow_html=True)


def eyebrow(text: str):
    st.markdown(f'<div class="eyebrow"><span style="width:6px;height:6px;border-radius:50%;background:{COLORS["c3"]};"></span>{text}</div>', unsafe_allow_html=True)