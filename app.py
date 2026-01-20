import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import numpy as np
import os
import time

# Page configuration
st.set_page_config(page_title="Airfoil CFD Tool", layout="wide", page_icon="✈️")

# Initialize session state for results
if 'results' not in st.session_state:
    st.session_state.results = None
if 'last_params' not in st.session_state:
    st.session_state.last_params = None

# Cached function for API calls
@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def run_xfoil_analysis(file_content: bytes, filename: str, reynolds: float, alpha: float, backend_url: str):
    """
    Run XFOIL analysis with caching and retry logic.
    """
    url = f"{backend_url}/upload_airfoil/"
    
    files = {"file": (filename, file_content, "text/plain")}
    data = {"reynolds": reynolds, "alpha": alpha}
    
    max_retries = 3
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            response = requests.post(url, files=files, data=data, timeout=90)
            
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    raise Exception(f"Server busy. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
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

# Custom CSS for better styling
st.markdown("""
    <style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        text-align: center;
        color: #666;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

# Header
st.markdown('<p class="main-header">✈️ Student Airfoil CFD Tool</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Analyze airfoil performance using XFOIL</p>', unsafe_allow_html=True)

# Sidebar with information and inputs
with st.sidebar:
    st.header("⚙️ Simulation Parameters")
    
    # Add cache info
    with st.expander("⚡ Performance Info"):
        st.markdown("""
        **Smart Caching Enabled!**
        
        Results are cached for 1 hour. If someone already analyzed the same airfoil 
        with the same parameters, you'll get instant results! 🚀
        
        This reduces server load and makes the tool faster for everyone.
        
        **Note:** Free tier has rate limits. Wait 30-60s between unique analyses.
        """)
    
    # Add educational info
    with st.expander("ℹ️ About This Tool"):
        st.markdown("""
        This tool uses **XFOIL**, a industry-standard panel method code for airfoil analysis.
        
        **How to use:**
        1. Upload a `.dat` file with airfoil coordinates
        2. Set Reynolds number and angle of attack
        3. Click analyze to run simulation
        
        **Common airfoil databases:**
        - [UIUC Airfoil Database](https://m-selig.ae.illinois.edu/ads/coord_database.html)
        - [Airfoil Tools](http://airfoiltools.com/)
        """)
    
    st.markdown("---")
    
    # Reynolds number input with presets
    st.subheader("Reynolds Number")
    reynolds_preset = st.selectbox(
        "Preset",
        ["Custom", "Model Aircraft (50k)", "Small UAV (100k)", "Light Aircraft (500k)", 
         "Glider (1M)", "Small Plane (3M)", "Airliner (6M)"],
        index=3
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
        "Reynolds Number",
        min_value=1_000,
        max_value=10_000_000,
        value=default_re,
        step=10_000,
        format="%d",
        help="Higher Reynolds = less viscous effects"
    )
    
    st.markdown("---")
    
    # Angle of attack
    st.subheader("Angle of Attack")
    alpha = st.slider(
        "Angle (degrees)",
        min_value=-20.0,
        max_value=20.0,
        value=5.0,
        step=0.5,
        help="Angle between chord line and freestream"
    )
    
    st.markdown("---")
    
    # Example airfoils
    with st.expander("📚 Example Airfoils"):
        st.markdown("""
        Try these popular airfoils:
        - **NACA 4412**: Classic cambered airfoil
        - **NACA 0012**: Symmetric airfoil
        - **Clark Y**: Vintage flat-bottom design
        - **S1223**: High-lift low-Re airfoil
        - **Eppler 387**: Sailplane airfoil
        """)

# Main content area
uploaded_file = st.file_uploader(
    "📁 Upload Airfoil .dat File",
    type="dat",
    help="Upload a file with airfoil x,y coordinates"
)

# Add Run Analysis button
run_analysis = st.button("🚀 Run Analysis", type="primary", disabled=(uploaded_file is None))

if uploaded_file is not None and run_analysis:
    # Use environment variable for backend URL
    backend_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
    
    # Prevent double-clicking
    if 'analyzing' in st.session_state and st.session_state.analyzing:
        st.warning("⏳ Analysis already in progress. Please wait...")
        st.stop()
    
    st.session_state.analyzing = True
    
    try:
        # Read file content for caching
        file_content = uploaded_file.getvalue()
        
        with st.spinner("Computing... (this may take 30-60s on free tier, or be instant if cached)"):
            result = run_xfoil_analysis(
                file_content=file_content,
                filename=uploaded_file.name,
                reynolds=reynolds,
                alpha=alpha,
                backend_url=backend_url
            )
        
        # Store results in session state
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
        
        # Special handling for rate limit with retry message
        if "Retrying" in error_msg:
            st.warning(f"⏳ {error_msg}")
            time.sleep(1)
            st.rerun()
        else:
            st.error(f"❌ Error: {error_msg}")
            
            # Add helpful tips
            if "rate-limited" in error_msg.lower() or "429" in error_msg:
                st.info("💡 **Tip:** The free tier has rate limits. Wait 60 seconds before trying again, or use a different airfoil/parameters to get cached results instantly.")

# Display results if they exist in session state
if st.session_state.results is not None:
    result = st.session_state.results
    last_params = st.session_state.last_params
    
    # Display parameter info
    st.info(f"📊 Showing results for: **{last_params['filename']}** | Re = {last_params['reynolds']:,} | α = {last_params['alpha']}°")
    
    # Display aerodynamic coefficients if available
    if "coefficients" in result and result["coefficients"]:
        st.markdown("---")
        st.subheader("📊 Aerodynamic Coefficients")
        
        coef_cols = st.columns(4)
        coeffs = result["coefficients"]
        
        metrics = [
            ("CL", "Lift Coefficient", "CL"),
            ("CD", "Drag Coefficient", "CD"),
            ("CM", "Moment Coefficient", "CM"),
            ("L/D", "Lift-to-Drag Ratio", None)
        ]
        
        for idx, (label, name, key) in enumerate(metrics):
            with coef_cols[idx]:
                if key and key in coeffs:
                    value = coeffs[key]
                    st.metric(label, f"{value:.4f}")
                elif label == "L/D" and "CL" in coeffs and "CD" in coeffs:
                    if coeffs["CD"] != 0:
                        ld_ratio = coeffs["CL"] / coeffs["CD"]
                        st.metric(label, f"{ld_ratio:.2f}")
                    else:
                        st.metric(label, "N/A")
    
    # Prepare data for plotting
    coords_before = pd.DataFrame(result["coords_before"], columns=["x", "y"])
    coords_after = pd.DataFrame(result["coords_after"], columns=["x", "y"])
    
    st.markdown("---")
    
    # Create two columns for plots
    plot_col1, plot_col2 = st.columns(2)
    
    with plot_col1:
        st.subheader("🛩️ Airfoil Geometry")
        fig1 = go.Figure()
        
        # Add airfoil shape
        fig1.add_trace(go.Scatter(
            x=coords_after["x"],
            y=coords_after["y"],
            mode='lines',
            name='Airfoil',
            line=dict(color='#667eea', width=3),
            fill='toself',
            fillcolor='rgba(102, 126, 234, 0.2)',
            hovertemplate='x: %{x:.4f}<br>y: %{y:.4f}<extra></extra>'
        ))
        
        # Add reference lines
        fig1.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.3)
        fig1.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.3)
        
        fig1.update_layout(
            title=last_params['filename'],
            xaxis_title="x/c",
            yaxis_title="y/c",
            height=400,
            hovermode='closest',
            plot_bgcolor='white',
            yaxis=dict(scaleanchor="x", scaleratio=1)
        )
        
        fig1.update_xaxes(showgrid=True, gridcolor='lightgray')
        fig1.update_yaxes(showgrid=True, gridcolor='lightgray')
        
        st.plotly_chart(fig1, use_container_width=True)
        
        # Show coordinate statistics
        with st.expander("🔍 Geometry Details"):
            st.write(f"**Number of points:** {len(coords_after)}")
            st.write(f"**Max thickness:** {(coords_after['y'].max() - coords_after['y'].min()):.4f}")
            st.write(f"**Chord length:** {coords_after['x'].max() - coords_after['x'].min():.4f}")
    
    with plot_col2:
        if result["cp_x"] and result["cp_values"]:
            st.subheader("📈 Pressure Distribution")
            
            cp_x = np.array(result["cp_x"])
            cp_values = np.array(result["cp_values"])
            
            fig2 = go.Figure()
            
            # Separate upper and lower surface
            mid_idx = len(cp_x) // 2
            
            # Upper surface
            fig2.add_trace(go.Scatter(
                x=cp_x[:mid_idx],
                y=cp_values[:mid_idx],
                mode='lines',
                name='Upper surface',
                line=dict(color='#3b82f6', width=3),
                hovertemplate='x/c: %{x:.4f}<br>Cp: %{y:.4f}<extra></extra>'
            ))
            
            # Lower surface
            fig2.add_trace(go.Scatter(
                x=cp_x[mid_idx:],
                y=cp_values[mid_idx:],
                mode='lines',
                name='Lower surface',
                line=dict(color='#ef4444', width=3),
                hovertemplate='x/c: %{x:.4f}<br>Cp: %{y:.4f}<extra></extra>'
            ))
            
            # Reference line
            fig2.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.3)
            
            fig2.update_layout(
                title=f"Re = {last_params['reynolds']:,.0f}, α = {last_params['alpha']}°",
                xaxis_title="x/c",
                yaxis_title="Cp",
                height=400,
                hovermode='closest',
                plot_bgcolor='white',
                yaxis=dict(autorange='reversed')  # Inverted y-axis
            )
            
            fig2.update_xaxes(showgrid=True, gridcolor='lightgray')
            fig2.update_yaxes(showgrid=True, gridcolor='lightgray')
            
            st.plotly_chart(fig2, use_container_width=True)
            
            # Add interpretation help
            with st.expander("📖 Understanding Cp"):
                st.markdown("""
                **Pressure Coefficient (Cp):**
                - Negative Cp = Lower pressure (suction)
                - Positive Cp = Higher pressure
                - Upper surface typically has lower pressure (negative Cp)
                - Lower surface has higher pressure (positive Cp)
                - The difference creates lift!
                """)
        else:
            st.warning("⚠️ No pressure coefficient data available")
    
    # Download results option
    st.markdown("---")
    if st.button("💾 Download Results as CSV"):
        csv_data = pd.DataFrame({
            'x': result["cp_x"],
            'Cp': result["cp_values"]
        })
        csv = csv_data.to_csv(index=False)
        st.download_button(
            label="Download Cp Data",
            data=csv,
            file_name=f"{last_params['filename'].replace('.dat', '')}_cp_results.csv",
            mime="text/csv"
        )

elif uploaded_file is not None:
    st.info("⚙️ Parameters set. Click '🚀 Run Analysis' button above to start simulation.")

else:
    # Show instructions when no file is uploaded
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
        - Choose appropriate Reynolds number
        - Select angle of attack
        - Upload your .dat file
        """)

# Footer
st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: #666;'>Built with Streamlit • Powered by XFOIL • For Educational Use</p>",
    unsafe_allow_html=True
)