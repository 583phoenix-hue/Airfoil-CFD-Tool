import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import os
import time
import io
import base64
from db_utils import increment_analysis_count


# ── Flow Visualization Helpers ───────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def compute_flow_field(coords_tuple, alpha_deg, n_streamlines=22, grid_res=220):
    """
    Vortex panel method flow field.
    N=160 panels for smooth velocity field.
    grid_res=220 for sharp heatmap resolution.
    Returns: sl_x, sl_y, speed_grid, x_arr, y_arr, coords
    """
    from matplotlib.path import Path as MplPath

    coords = np.array(coords_tuple)
    alpha_r = np.radians(alpha_deg)
    U0 = 1.0

    xc = coords[:, 0]
    yc = coords[:, 1]
    chord = xc.max() - xc.min()

    # ── 1. Build panels (N=160 for smooth field) ──────────────────────────
    N = min(160, len(coords) - 1)
    dx_ = np.diff(xc); dy_ = np.diff(yc)
    arc = np.concatenate([[0], np.cumsum(np.hypot(dx_, dy_))])
    arc_u = np.linspace(0, arc[-1], N + 1)
    xp = np.interp(arc_u, arc, xc)
    yp = np.interp(arc_u, arc, yc)

    xm = 0.5 * (xp[:-1] + xp[1:])
    ym = 0.5 * (yp[:-1] + yp[1:])
    dx = xp[1:] - xp[:-1]
    dy = yp[1:] - yp[:-1]
    panel_len = np.hypot(dx, dy)
    sin_t = dy / panel_len
    cos_t = dx / panel_len
    nx_panel = -sin_t
    ny_panel =  cos_t

    # ── 2. Influence matrix ───────────────────────────────────────────────
    A = np.zeros((N + 1, N + 1))

    def vortex_vel(xi, yi, xj1, yj1, xj2, yj2):
        dxj = xj2 - xj1; dyj = yj2 - yj1
        Lj  = np.hypot(dxj, dyj)
        cos_j = dxj / Lj; sin_j = dyj / Lj
        xlt =  (xi - xj1) * cos_j + (yi - yj1) * sin_j
        ylt = -(xi - xj1) * sin_j + (yi - yj1) * cos_j
        r1sq = xlt**2 + ylt**2 + 1e-14
        r2sq = (xlt - Lj)**2 + ylt**2 + 1e-14
        theta1 = np.arctan2(ylt, xlt)
        theta2 = np.arctan2(ylt, xlt - Lj)
        u_loc = -(theta2 - theta1) / (2 * np.pi)
        v_loc =  0.5 / (2 * np.pi) * np.log(r1sq / r2sq)
        u = u_loc * cos_j - v_loc * sin_j
        v = u_loc * sin_j + v_loc * cos_j
        return u, v

    for i in range(N):
        for j in range(N):
            u, v = vortex_vel(xm[i], ym[i], xp[j], yp[j], xp[j+1], yp[j+1])
            A[i, j] += u * nx_panel[i] + v * ny_panel[i]
        A[i, i] += 0.5

    rhs = np.zeros(N + 1)
    rhs[:N] = -(U0 * np.cos(alpha_r) * nx_panel + U0 * np.sin(alpha_r) * ny_panel)
    A[N, 0]   =  1.0
    A[N, N-1] =  1.0
    rhs[N]    =  0.0

    # ── 3. Solve ──────────────────────────────────────────────────────────
    try:
        gamma = np.linalg.solve(A, rhs)
    except np.linalg.LinAlgError:
        gamma = np.linalg.lstsq(A, rhs, rcond=None)[0]

    airfoil_path = MplPath(coords)
    gamma_a = gamma[:N]

    # ── 4. Surface tangential speed ───────────────────────────────────────
    Vt_surface = np.zeros(N)
    for i in range(N):
        Vt_surface[i] = U0 * (np.cos(alpha_r) * cos_t[i] + np.sin(alpha_r) * sin_t[i])
        xj1=xp[:N]; yj1=yp[:N]; xj2=xp[1:N+1]; yj2=yp[1:N+1]
        dxj=xj2-xj1; dyj=yj2-yj1; Lj=np.hypot(dxj,dyj)+1e-14
        cj=dxj/Lj; sj=dyj/Lj
        xlt=(xm[i]-xj1)*cj+(ym[i]-yj1)*sj
        ylt=-(xm[i]-xj1)*sj+(ym[i]-yj1)*cj
        r1sq=xlt**2+ylt**2+1e-14; r2sq=(xlt-Lj)**2+ylt**2+1e-14
        th1=np.arctan2(ylt,xlt); th2=np.arctan2(ylt,xlt-Lj)
        ul=-(th2-th1)/(2*np.pi); vl=0.5/(2*np.pi)*np.log(r1sq/r2sq)
        ug=ul*cj-vl*sj; vg=ul*sj+vl*cj
        Vt_surface[i] += float(np.dot(gamma_a, ug*cos_t[i]+vg*sin_t[i])) + 0.5*gamma_a[i]
    Vt_surface = np.abs(Vt_surface)

    # ── 5. Velocity grid (vectorised, high-res) ───────────────────────────
    pad_x = chord * 0.60
    pad_y = chord * 0.60
    x1g = xc.min() - pad_x;  x2g = xc.max() + pad_x
    y1g = yc.min() - pad_y;  y2g = yc.max() + pad_y

    x_arr = np.linspace(x1g, x2g, grid_res)
    y_arr = np.linspace(y1g, y2g, grid_res)
    Xg, Yg = np.meshgrid(x_arr, y_arr)

    Ug = U0 * np.cos(alpha_r) * np.ones_like(Xg)
    Vg = U0 * np.sin(alpha_r) * np.ones_like(Yg)

    Xf = Xg.ravel(); Yf = Yg.ravel()
    for j in range(N):
        u_ind, v_ind = vortex_vel(Xf, Yf, xp[j], yp[j], xp[j+1], yp[j+1])
        Ug.ravel()[:] += gamma_a[j] * u_ind
        Vg.ravel()[:] += gamma_a[j] * v_ind

    raw_speed = np.hypot(Ug, Vg)

    # ── 6. Blended speed grid ─────────────────────────────────────────────
    # Blend surface tangential speed into the off-body field within 0.30c.
    # Hard cutoff at 0.30c prevents far-field contamination from slow panels.
    pts_flat = np.c_[Xf, Yf]
    panel_pts = np.c_[xm, ym]
    diff = pts_flat[:, None, :] - panel_pts[None, :, :]
    dist2 = (diff**2).sum(axis=2)
    nearest_idx = np.argmin(dist2, axis=1)
    dist_flat = np.sqrt(dist2[np.arange(len(Xf)), nearest_idx])
    surface_spd_flat = Vt_surface[nearest_idx]

    blend_radius = chord * 0.30
    blend_flat = np.where(
        dist_flat < blend_radius,
        np.exp(-dist_flat / (chord * 0.15)),
        0.0
    )
    blended_flat = blend_flat * surface_spd_flat + (1.0 - blend_flat) * raw_speed.ravel()
    speed_grid = blended_flat.reshape(grid_res, grid_res)

    # Interior: 0.0 (dark blue). No NaN — avoids Plotly heatmap artefacts.
    pts_xy = np.c_[Xg.ravel(), Yg.ravel()]
    inside = airfoil_path.contains_points(pts_xy, radius=-1e-4).reshape(grid_res, grid_res)
    speed_grid[inside] = 0.0
    Ug[inside] = np.nan
    Vg[inside] = np.nan

    # ── 7. Streamline tracer ──────────────────────────────────────────────
    def field_velocity(cx, cy):
        six = int(np.clip(np.searchsorted(x_arr, cx) - 1, 0, grid_res - 2))
        siy = int(np.clip(np.searchsorted(y_arr, cy) - 1, 0, grid_res - 2))
        ffx = (cx - x_arr[six]) / (x_arr[six+1] - x_arr[six] + 1e-12)
        ffy = (cy - y_arr[siy]) / (y_arr[siy+1] - y_arr[siy] + 1e-12)
        uu = (Ug[siy,six]*(1-ffx)*(1-ffy) + Ug[siy,six+1]*ffx*(1-ffy) +
              Ug[siy+1,six]*(1-ffx)*ffy   + Ug[siy+1,six+1]*ffx*ffy)
        vv = (Vg[siy,six]*(1-ffx)*(1-ffy) + Vg[siy,six+1]*ffx*(1-ffy) +
              Vg[siy+1,six]*(1-ffx)*ffy   + Vg[siy+1,six+1]*ffx*ffy)
        return float(uu), float(vv)

    y_starts = np.linspace(y1g + 0.03, y2g - 0.03, n_streamlines)
    sl_x, sl_y = [], []
    dt = 0.004

    for ys in y_starts:
        px, py = [x1g + 0.02], [ys]
        for _ in range(800):
            cx, cy = px[-1], py[-1]
            if cx > x2g or cx < x1g or cy > y2g or cy < y1g:
                break
            uu, vv = field_velocity(cx, cy)
            spd = float(np.hypot(uu, vv))
            if np.isnan(uu) or np.isnan(vv) or spd < 1e-6:
                break
            nx_pt = cx + dt * uu
            ny_pt = cy + dt * vv
            if airfoil_path.contains_points([[nx_pt, ny_pt]], radius=-1e-4)[0]:
                break
            px.append(nx_pt); py.append(ny_pt)
        if len(px) > 5:
            sl_x.append(px)
            sl_y.append(py)

    return sl_x, sl_y, speed_grid, x_arr, y_arr, coords.tolist()


@st.cache_data(show_spinner=False)
def render_heatmap_png(speed_grid_tuple, x_arr_tuple, y_arr_tuple, coords_tuple,
                       plot_xmin, plot_xmax, plot_ymin, plot_ymax):
    """
    Renders heatmap + airfoil fill to PNG via matplotlib.
    Uses bicubic interpolation for smooth colour transitions.
    Embedded as layout.images in Plotly — immune to animation frame resets.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from matplotlib.patches import Polygon

    speed_grid = np.array(speed_grid_tuple)
    x_arr = np.array(x_arr_tuple)
    y_arr = np.array(y_arr_tuple)
    coords = np.array(coords_tuple)

    U0 = 1.0
    s_min = 0.0
    s_max = U0 * 2.2

    cmap_colors = [
        (0.00, "#1d4ed8"),
        (0.20, "#2563eb"),
        (0.45, "#06b6d4"),
        (0.65, "#22c55e"),
        (0.80, "#facc15"),
        (0.92, "#f97316"),
        (1.00, "#ef4444"),
    ]
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "aerolab", [(v, c) for v, c in cmap_colors]
    )

    fig_w = plot_xmax - plot_xmin
    fig_h = plot_ymax - plot_ymin
    dpi = 180          # higher DPI for sharpness
    px_w = 1100        # wider render for more detail
    px_h = int(px_w * fig_h / fig_w)

    fig, ax = plt.subplots(figsize=(px_w/dpi, px_h/dpi), dpi=dpi)
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#0f172a")

    norm_grid = np.clip((speed_grid - s_min) / (s_max - s_min), 0, 1)

    # bicubic interpolation — smooth colour field, no blocky artefacts
    ax.imshow(
        norm_grid,
        origin="lower",
        extent=[x_arr[0], x_arr[-1], y_arr[0], y_arr[-1]],
        cmap=cmap, vmin=0, vmax=1,
        aspect="auto",
        interpolation="bicubic"   # key upgrade from bilinear
    )

    # Airfoil fill
    airfoil_patch = Polygon(
        coords, closed=True,
        facecolor="#0f172a", edgecolor="#a5b4fc",
        linewidth=1.5, zorder=3
    )
    ax.add_patch(airfoil_patch)

    ax.set_xlim(plot_xmin, plot_xmax)
    ax.set_ylim(plot_ymin, plot_ymax)
    ax.axis("off")
    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi,
                facecolor="#0f172a", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def build_flow_animation(sl_x, sl_y, speed_grid, x_arr, y_arr, coords, alpha_deg, show_particles=True, show_streamlines=True):
    """
    layout.images[0] : permanent PNG background (heatmap + airfoil fill)
    Trace 0 : streamlines (static)
    Trace 1 : airfoil outline (static)
    Trace 2 : white particles (animated — only trace updated in frames)
    Trace 3 : invisible colorbar dummy
    """
    airfoil_x = [p[0] for p in coords] + [coords[0][0]]
    airfoil_y = [p[1] for p in coords] + [coords[0][1]]

    # Axis range shown in Plotly
    plot_xmin = min(airfoil_x) - 0.4
    plot_xmax = max(airfoil_x) + 0.4
    plot_ymin = min(airfoil_y) - 0.55
    plot_ymax = max(airfoil_y) + 0.55

    # PNG render bounds: extend well beyond axis range so the image fully
    # covers the plot area with no dark gaps at the edges.
    # layout.images are anchored to data coordinates so this is exact.
    xpad = (plot_xmax - plot_xmin) * 0.08
    ypad = (plot_ymax - plot_ymin) * 0.08
    img_xmin = plot_xmin - xpad
    img_xmax = plot_xmax + xpad
    img_ymin = plot_ymin - ypad
    img_ymax = plot_ymax + ypad

    heatmap_png = render_heatmap_png(
        tuple(map(tuple, speed_grid.tolist())),
        tuple(x_arr.tolist()),
        tuple(y_arr.tolist()),
        tuple(map(tuple, coords)),
        img_xmin, img_xmax, img_ymin, img_ymax
    )

    n_frames = 50

    # ── Trace 0: Streamlines ──────────────────────────────────────────────
    all_sx, all_sy = [], []
    for sx, sy in zip(sl_x, sl_y):
        n = min(len(sx), len(sy))
        all_sx.extend(sx[:n] + [None])
        all_sy.extend(sy[:n] + [None])

    trace_lines = go.Scatter(
        x=all_sx, y=all_sy,
        mode="lines",
        line=dict(width=1.0, color="rgba(255,255,255,0.35)"),
        hoverinfo="skip", showlegend=False,
        visible=show_streamlines,
    )

    # ── Trace 1: Airfoil outline ──────────────────────────────────────────
    trace_airfoil = go.Scatter(
        x=airfoil_x, y=airfoil_y,
        mode="lines",
        line=dict(color="#a5b4fc", width=1.5),
        fill="toself",
        fillcolor="rgba(15,23,42,1.0)",
        hoverinfo="skip", showlegend=False
    )

    # ── Arc-length particle placement ─────────────────────────────────────
    sl_arc = []
    for sx, sy in zip(sl_x, sl_y):
        n = min(len(sx), len(sy))
        dists = [0.0]
        for i in range(1, n):
            dists.append(dists[-1] + np.hypot(sx[i]-sx[i-1], sy[i]-sy[i-1]))
        sl_arc.append(dists)

    total_arcs = [a[-1] for a in sl_arc if len(a) > 1]
    period = float(np.median(total_arcs)) if total_arcs else 1.0

    particles_per_streamline = 5
    rng = np.random.default_rng(42)
    streamline_jitter = rng.uniform(0, 1, len(sl_x))

    frame_dots = []
    for f in range(n_frames):
        fdx, fdy = [], []
        for si, (sx, sy, arc) in enumerate(zip(sl_x, sl_y, sl_arc)):
            n = min(len(sx), len(sy))
            if n < 4:
                continue
            arc_arr = np.array(arc[:n])
            total = arc_arr[-1]
            if total < 1e-6:
                continue
            for p in range(particles_per_streamline):
                t_frac = ((f / n_frames) + streamline_jitter[si] + p / particles_per_streamline) % 1.0
                target_arc = (t_frac * period) % total
                idx = int(np.clip(np.searchsorted(arc_arr, target_arc, side='right') - 1, 0, n - 1))
                fdx.append(sx[idx])
                fdy.append(sy[idx])
        frame_dots.append((fdx, fdy))

    # ── Trace 2: Particles ────────────────────────────────────────────────
    dx0, dy0 = frame_dots[0]
    trace_particles = go.Scatter(
        x=dx0, y=dy0,
        mode="markers",
        marker=dict(size=5, color="white", opacity=0.9, line=dict(width=0)),
        hoverinfo="skip", showlegend=False,
        visible=show_particles,
    )

    # ── Trace 3: Invisible colorbar ───────────────────────────────────────
    colorscale_for_bar = [
        [0.00, "#1d4ed8"], [0.20, "#2563eb"], [0.45, "#06b6d4"],
        [0.65, "#22c55e"], [0.80, "#facc15"], [0.92, "#f97316"], [1.00, "#ef4444"],
    ]
    trace_colorbar = go.Scatter(
        x=[None], y=[None],
        mode="markers",
        marker=dict(
            size=0, color=[0, 1],
            colorscale=colorscale_for_bar,
            cmin=0, cmax=1,
            showscale=True,
            colorbar=dict(
                title=dict(text="V / V∞", font=dict(color="white", size=12)),
                tickvals=[0, 0.45, 0.65, 0.80, 1.0],
                ticktext=["0", "1.0×", "1.4×", "1.8×", "2.2×"],
                tickfont=dict(color="white"),
                thickness=12, len=0.6, x=1.02,
            )
        ),
        hoverinfo="skip", showlegend=False
    )

    # ── Frames: only update trace 2 (particles) ───────────────────────────
    frames = []
    for f in range(n_frames):
        fdx, fdy = frame_dots[f]
        frames.append(go.Frame(
            data=[go.Scatter(
                x=fdx, y=fdy,
                mode="markers",
                marker=dict(size=5, color="white", opacity=0.9, line=dict(width=0))
            )],
            traces=[2],
            name=str(f)
        ))

    fig = go.Figure(
        data=[trace_lines, trace_airfoil, trace_particles, trace_colorbar],
        frames=frames,
        layout=go.Layout(
            title=dict(
                text=f"Airflow  |  α = {alpha_deg}°",
                font=dict(size=14, color="white"),
                x=0.5, xanchor="center"
            ),
            xaxis=dict(
                title="x/c", showgrid=False, zeroline=False,
                range=[plot_xmin, plot_xmax]
            ),
            yaxis=dict(
                title="y/c", showgrid=False, zeroline=False,
                scaleanchor="x", scaleratio=1,
                range=[plot_ymin, plot_ymax]
            ),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="#0f172a",
            font=dict(color="white"),
            height=510,
            margin=dict(l=50, r=90, t=40, b=70),
            images=[dict(
                source=heatmap_png,
                xref="x", yref="y",
                x=img_xmin, y=img_ymax,
                sizex=img_xmax - img_xmin,
                sizey=img_ymax - img_ymin,
                sizing="stretch",
                layer="below",
                opacity=1.0,
            )],
            updatemenus=[dict(
                type="buttons", showactive=False,
                x=0.0, y=-0.08,
                xanchor="left", yanchor="top",
                direction="right",
                buttons=[
                    dict(
                        label="▶  Play", method="animate",
                        args=[None, dict(
                            frame=dict(duration=60, redraw=False),
                            fromcurrent=True,
                            transition=dict(duration=0),
                            mode="immediate"
                        )]
                    ),
                    dict(
                        label="⏸  Pause", method="animate",
                        args=[[None], dict(
                            frame=dict(duration=0, redraw=False),
                            mode="immediate",
                            transition=dict(duration=0)
                        )]
                    )
                ],
                font=dict(color="#0f172a"),
                bgcolor="#e2e8f0",
                bordercolor="#94a3b8",
                borderwidth=1,
            )]
        )
    )
    return fig


st.set_page_config(page_title="Airfoil Analysis - AeroLab", layout="wide", page_icon="✈️",
                   initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        [data-testid="stSidebarNav"]    {display: none;}
        [data-testid="collapsedControl"] {display: none;}
        section[data-testid="stSidebar"] {display: none;}
        footer {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        div[data-testid="stToolbar"]    {visibility: hidden; height: 0%;}
        div[data-testid="stDecoration"] {visibility: hidden; height: 0%;}
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

# ── Backend Health Check ─────────────────────────────────────────────────────
BACKEND_URL = "https://aerolab-backend.onrender.com"
IS_LOCAL = os.environ.get("LOCAL_DEV", "false").lower() == "true"

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

backend_status = "online" if IS_LOCAL else check_backend()

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

# ── Session state ─────────────────────────────────────────────────────────────
if 'results' not in st.session_state:
    st.session_state.results = None
if 'last_params' not in st.session_state:
    st.session_state.last_params = None
if 'show_particles' not in st.session_state:
    st.session_state.show_particles = True
if 'show_streamlines' not in st.session_state:
    st.session_state.show_streamlines = True

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

# ── Layout ────────────────────────────────────────────────────────────────────
left_col, right_col = st.columns([1, 3])

with left_col:
    st.markdown('<div class="panel-title">⚙️ Parameters</div>', unsafe_allow_html=True)

    if st.button("← Home", use_container_width=True):
        st.switch_page("app.py")

    st.markdown("<br>", unsafe_allow_html=True)

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
        min_value=1_000, max_value=10_000_000,
        value=default_re, step=10_000, format="%d",
        help="Higher Reynolds = less viscous effects",
        label_visibility="collapsed"
    )

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown('<p class="param-label">Angle of Attack</p>', unsafe_allow_html=True)
    alpha = st.slider(
        "Angle of Attack",
        min_value=-20.0, max_value=20.0, value=5.0, step=0.5,
        help="Angle between chord line and freestream",
        label_visibility="collapsed"
    )
    st.caption(f"Selected: **{alpha}°**")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("---")

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

# ── Main content ──────────────────────────────────────────────────────────────
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

    # ── Results ───────────────────────────────────────────────────────────
    if st.session_state.results is not None:
        result = st.session_state.results
        last_params = st.session_state.last_params

        st.info(f"📊 **{last_params['filename']}** | Re = {last_params['reynolds']:,} | α = {last_params['alpha']}°")

        if "coefficients" in result and result["coefficients"]:
            st.markdown("---")
            st.subheader("📊 Aerodynamic Coefficients")
            coeffs = result["coefficients"]

            if "CL" in coeffs and "CD" in coeffs:
                ld = coeffs["CL"] / coeffs["CD"] if coeffs["CD"] != 0 else 0
                if coeffs["CL"] < -0.1:
                    st.warning("⚠️ **Negative Lift Detected!** The airfoil is generating downforce.")
                elif abs(coeffs["CL"]) < 0.001:
                    st.info("ℹ️ **Near-Zero Lift:** Symmetric airfoil at zero AoA — L/D not meaningful.")
                elif abs(last_params['alpha']) >= 12 and (coeffs["CD"] > 0.15 or ld < 5):
                    st.error("🚨 **Possible Stall Condition!** High drag and low L/D suggests flow separation.")

            coef_cols = st.columns(3)
            for idx, (label, key) in enumerate([("CL", "CL"), ("CD", "CD"), ("L/D", None)]):
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

        # ── Airflow Visualization ─────────────────────────────────────────
        st.markdown("---")
        st.subheader("🌊 Airflow Visualization")
        st.caption("Speed heatmap with animated flow particles. Press ▶ Play to animate. Use the camera icon to save PNG.")
        try:
            with st.spinner("Computing flow field... (higher resolution may take ~60s on first run)"):
                sl_x, sl_y, speed_grid, x_arr, y_arr, coords_list = compute_flow_field(
                    tuple(map(tuple, result["coords_after"])),
                    last_params['alpha']
                )
            flow_fig = build_flow_animation(
                sl_x, sl_y, speed_grid, x_arr, y_arr, coords_list, last_params['alpha']
            )
            st.plotly_chart(flow_fig, use_container_width=True)
        except Exception as e:
            st.error(f"⚠️ Visualization error: {e}")

        with st.expander("ℹ️ About This Visualization"):
            st.markdown("""
            **Potential Flow (Vortex Panel Method) — 160 panels, 220×220 grid**
            - **Colour field** — speed at every point: blue = slow (high pressure), red = fast (low pressure)
            - **White lines** — streamlines showing flow direction
            - **White dots** — animated fluid particles; they move faster where flow is faster

            *Inviscid potential flow — does not model stall or boundary layer separation.*
            """)
        # ─────────────────────────────────────────────────────────────────

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