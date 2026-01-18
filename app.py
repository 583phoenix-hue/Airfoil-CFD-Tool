import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# Page configuration
st.set_page_config(page_title="Airfoil CFD Tool", layout="wide", page_icon="✈️")

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

if uploaded_file is not None:
    # Create two columns for layout
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.info("🔄 Running XFOIL simulation...")
    
    # Use environment variable for backend URL (Railway will set this)
    backend_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
    url = f"{backend_url}/upload_airfoil/"
    
    try:
        files = {"file": (uploaded_file.name, uploaded_file, "text/plain")}
        data = {"reynolds": reynolds, "alpha": alpha}
        
        with st.spinner("Computing..."):
            response = requests.post(url, files=files, data=data, timeout=30)
        
        if response.status_code != 200:
            st.error(f"❌ Server Error: {response.text}")
        else:
            result = response.json()
            st.success("✅ Simulation completed successfully!")
            
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
                fig1, ax1 = plt.subplots(figsize=(8, 4))
                ax1.plot(coords_after["x"], coords_after["y"], 'b-', linewidth=2, label="Airfoil")
                ax1.fill(coords_after["x"], coords_after["y"], alpha=0.3)
                ax1.axhline(y=0, color='k', linestyle='--', alpha=0.3, linewidth=0.5)
                ax1.axvline(x=0, color='k', linestyle='--', alpha=0.3, linewidth=0.5)
                ax1.set_aspect("equal", "box")
                ax1.set_xlabel("x/c", fontsize=10)
                ax1.set_ylabel("y/c", fontsize=10)
                ax1.set_title(f"{uploaded_file.name}", fontsize=11)
                ax1.grid(True, alpha=0.3)
                ax1.legend()
                st.pyplot(fig1)
                
                # Show coordinate statistics
                with st.expander("📐 Geometry Details"):
                    st.write(f"**Number of points:** {len(coords_after)}")
                    st.write(f"**Max thickness:** {(coords_after['y'].max() - coords_after['y'].min()):.4f}")
                    st.write(f"**Chord length:** {coords_after['x'].max() - coords_after['x'].min():.4f}")
            
            with plot_col2:
                if result["cp_x"] and result["cp_values"]:
                    st.subheader("📈 Pressure Distribution")
                    fig2, ax2 = plt.subplots(figsize=(8, 4))
                    
                    cp_x = np.array(result["cp_x"])
                    cp_values = np.array(result["cp_values"])
                    
                    # Separate upper and lower surface
                    mid_idx = len(cp_x) // 2
                    ax2.plot(cp_x[:mid_idx], cp_values[:mid_idx], 'b-', linewidth=2, label="Upper surface")
                    ax2.plot(cp_x[mid_idx:], cp_values[mid_idx:], 'r-', linewidth=2, label="Lower surface")
                    
                    ax2.set_xlabel("x/c", fontsize=10)
                    ax2.set_ylabel("Cp", fontsize=10)
                    ax2.set_title(f"Re = {reynolds:,.0f}, α = {alpha}°", fontsize=11)
                    ax2.invert_yaxis()
                    ax2.grid(True, alpha=0.3)
                    ax2.legend()
                    ax2.axhline(y=0, color='k', linestyle='--', alpha=0.3, linewidth=0.5)
                    st.pyplot(fig2)
                    
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
                    file_name=f"{uploaded_file.name.replace('.dat', '')}_cp_results.csv",
                    mime="text/csv"
                )
    
    except requests.exceptions.Timeout:
        st.error("⏱️ Request timeout. The simulation took too long. Try simpler geometry or different parameters.")
    except requests.exceptions.ConnectionError:
        st.error("🔌 Cannot connect to server. Make sure the FastAPI server is running (python main.py)")
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Request failed: {e}")
    except Exception as e:
        st.error(f"❌ Unexpected error: {e}")

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