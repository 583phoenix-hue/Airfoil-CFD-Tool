import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import os
import time
import io
import base64
import json
import streamlit.components.v1 as components
from db_utils import increment_analysis_count


# ── Flow Visualization Helpers ───────────────────────────────────────────────

# ── LBM Wind Tunnel component ────────────────────────────────────────────────
_LBM_TEMPLATE = os.path.join(os.path.dirname(__file__), "airfoil_flow_lbm_aerolab.html")

def build_lbm_component(coords_after, airfoil_name: str = "") -> None:
    """
    Render the interactive LBM wind-tunnel visualisation using the user's
    actual parsed airfoil coordinates injected into the WebGL2 component.
    """
    try:
        with open(_LBM_TEMPLATE, "r") as f:
            template = f.read()
    except FileNotFoundError:
        st.error(
            f"⚠️ LBM visualisation template not found. Expected: `{_LBM_TEMPLATE}`"
        )
        return

    coords_json = json.dumps(
        [[round(float(x), 6), round(float(y), 6)] for x, y in coords_after]
    )
    name_json = json.dumps(airfoil_name or "Uploaded airfoil")

    html = template.replace("%%USER_COORDS%%", coords_json)
    html = html.replace("%%USER_NAME%%", name_json)

    components.html(html, height=640, scrolling=False)


@st.cache_data(show_spinner=False)
def compute_flow_field(coords_tuple, alpha_deg, n_streamlines=22, grid_res=220):
    """
    Vortex panel method — constant-strength vortex panels.
    N=160 cosine-spaced panels. Zero-diagonal influence matrix with Kutta
    condition replacing the last row. Gives symmetric solutions for symmetric
    airfoils and physically correct off-body velocity fields for visualization.
    Returns: sl_x, sl_y, speed_grid, x_arr, y_arr, coords
    """
    from matplotlib.path import Path as MplPath

    coords = np.array(coords_tuple)
    alpha_r = np.radians(alpha_deg)
    U0 = 1.0

    xc = coords[:, 0]
    yc = coords[:, 1]
    chord = xc.max() - xc.min()

    # ── 1. Cosine-spaced panels ────────────────────────────────────────────
    N = 160
    dx_ = np.diff(xc); dy_ = np.diff(yc)
    arc = np.concatenate([[0], np.cumsum(np.hypot(dx_, dy_))])
    beta_arr = np.linspace(0, np.pi, N + 1)
    arc_u = arc[-1] * 0.5 * (1.0 - np.cos(beta_arr))
    xp = np.interp(arc_u, arc, xc)
    yp = np.interp(arc_u, arc, yc)

    xm = 0.5 * (xp[:-1] + xp[1:])
    ym = 0.5 * (yp[:-1] + yp[1:])
    dx = xp[1:] - xp[:-1]
    dy = yp[1:] - yp[:-1]
    panel_len = np.hypot(dx, dy)
    ct = dx / panel_len
    st = dy / panel_len
    nx = -st   # inward normals
    ny =  ct

    # ── 2. Vortex panel velocity kernel ───────────────────────────────────
    def vortex_vel(xi, yi, x1, y1, x2, y2):
        dxj = x2 - x1; dyj = y2 - y1
        Lj  = np.hypot(dxj, dyj) + 1e-14
        c = dxj / Lj; s = dyj / Lj
        xlt =  (xi - x1) * c + (yi - y1) * s
        ylt = -(xi - x1) * s + (yi - y1) * c
        r1sq = xlt**2 + ylt**2 + 1e-14
        r2sq = (xlt - Lj)**2 + ylt**2 + 1e-14
        t1 = np.arctan2(ylt, xlt)
        t2 = np.arctan2(ylt, xlt - Lj)
        u_l = -(t2 - t1) / (2.0 * np.pi)
        v_l =  0.5 / (2.0 * np.pi) * np.log(r1sq / r2sq)
        return u_l * c - v_l * s, u_l * s + v_l * c

    # ── 3. Influence matrix + Kutta ────────────────────────────────────────
    # Zero diagonal (normal self-influence = 0 for vortex panels).
    # Last row replaced with Kutta: gamma[0] + gamma[N-1] = 0.
    A = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            if i != j:
                ug, vg = vortex_vel(xm[i], ym[i], xp[j], yp[j], xp[j+1], yp[j+1])
                A[i, j] = ug * nx[i] + vg * ny[i]

    A[N-1, :]   = 0.0
    A[N-1, 0]   = 1.0
    A[N-1, N-1] = 1.0

    rhs = -(U0 * np.cos(alpha_r) * nx + U0 * np.sin(alpha_r) * ny)
    rhs[N-1] = 0.0

    # ── 4. Solve — cosine default, uniform fallback for ill-conditioned ────
    # Cosine spacing can create tiny LE panels on high-camber airfoils
    # (e.g. S1223), blowing up condition number. Detect via max|gamma| > 50
    # and retry with uniform arc-length spacing.
    try:
        gamma_a = np.linalg.solve(A, rhs)
    except np.linalg.LinAlgError:
        gamma_a = np.linalg.lstsq(A, rhs, rcond=None)[0]

    if np.max(np.abs(gamma_a)) > 500.0:
        arc_u2 = np.linspace(0, arc[-1], N + 1)
        xp = np.interp(arc_u2, arc, xc); yp = np.interp(arc_u2, arc, yc)
        xm = 0.5*(xp[:-1]+xp[1:]); ym = 0.5*(yp[:-1]+yp[1:])
        dx = xp[1:]-xp[:-1]; dy = yp[1:]-yp[:-1]
        panel_len = np.hypot(dx, dy)
        ct = dx/panel_len; st = dy/panel_len
        nx = -st; ny = ct
        A2 = np.zeros((N, N))
        for i in range(N):
            for j in range(N):
                if i != j:
                    ug, vg = vortex_vel(xm[i], ym[i], xp[j], yp[j], xp[j+1], yp[j+1])
                    A2[i, j] = ug * nx[i] + vg * ny[i]
        A2[N-1,:]=0.0; A2[N-1,0]=1.0; A2[N-1,N-1]=1.0
        rhs2 = -(U0*np.cos(alpha_r)*nx + U0*np.sin(alpha_r)*ny)
        rhs2[N-1] = 0.0
        try:
            gamma_a = np.linalg.solve(A2, rhs2)
        except np.linalg.LinAlgError:
            gamma_a = np.linalg.lstsq(A2, rhs2, rcond=None)[0]

    airfoil_path = MplPath(coords)

    # ── 5. Off-body velocity grid ──────────────────────────────────────────
    pad = chord * 0.60
    x1g = xc.min() - pad;  x2g = xc.max() + pad
    y1g = yc.min() - pad;  y2g = yc.max() + pad

    x_arr = np.linspace(x1g, x2g, grid_res)
    y_arr = np.linspace(y1g, y2g, grid_res)
    Xg, Yg = np.meshgrid(x_arr, y_arr)

    Ug = U0 * np.cos(alpha_r) * np.ones_like(Xg)
    Vg = U0 * np.sin(alpha_r) * np.ones_like(Yg)

    Xf = Xg.ravel(); Yf = Yg.ravel()
    for j in range(N):
        ug, vg = vortex_vel(Xf, Yf, xp[j], yp[j], xp[j+1], yp[j+1])
        Ug.ravel()[:] += gamma_a[j] * ug
        Vg.ravel()[:] += gamma_a[j] * vg

    # ── 6. Interior mask + speed grid ─────────────────────────────────────
    pts_xy = np.c_[Xg.ravel(), Yg.ravel()]
    inside = airfoil_path.contains_points(pts_xy, radius=-1e-4).reshape(grid_res, grid_res)

    speed = np.hypot(Ug, Vg)
    outside_vals = speed[~inside]
    # Use 99.99th percentile — 99.9 was too aggressive and clipped real
    # near-surface velocity peaks, washing out the suction peak colours.
    p999 = float(np.percentile(outside_vals, 99.99))
    speed = np.clip(speed, 0.0, p999)
    speed[inside] = 0.0
    Ug[inside]    = np.nan
    Vg[inside]    = np.nan
    speed_grid    = speed

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
    s_max = U0 * 2.0   # fixed scale — enables cross-airfoil comparison

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
    dpi = 180
    px_w = 1100
    px_h = int(px_w * fig_h / fig_w)

    fig, ax = plt.subplots(figsize=(px_w/dpi, px_h/dpi), dpi=dpi)
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#0f172a")

    norm_grid = np.clip((speed_grid - s_min) / (s_max - s_min), 0, 1)

    ax.imshow(
        norm_grid,
        origin="lower",
        extent=[x_arr[0], x_arr[-1], y_arr[0], y_arr[-1]],
        cmap=cmap, vmin=0, vmax=1,
        aspect="auto",
        interpolation="bicubic"
    )

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


def build_bl_overlay(coords, bl_data):
    import numpy as np
    coords_arr = np.array(coords)
    centroid_x = coords_arr[:, 0].mean()
    centroid_y = coords_arr[:, 1].mean()

    def offset_surface(rows, side):
        if len(rows) < 2:
            return [], []
        xs = np.array([r["x"] for r in rows])
        ys = np.array([r["y"] for r in rows])
        ds = np.array([r["dstar"] for r in rows])
        tx = np.gradient(xs)
        ty = np.gradient(ys)
        mag = np.hypot(tx, ty) + 1e-12
        tx /= mag; ty /= mag
        nx = -ty if side == "upper" else ty
        ny =  tx if side == "upper" else -tx
        for i in range(len(xs)):
            if (nx[i]*(xs[i]-centroid_x) + ny[i]*(ys[i]-centroid_y)) < 0:
                nx[i] = -nx[i]; ny[i] = -ny[i]
        return (xs + ds*nx).tolist(), (ys + ds*ny).tolist()

    def surface_point_at_x(rows, x_tr):
        if x_tr is None:
            return None
        xs = [r["x"] for r in rows]
        ys = [r["y"] for r in rows]
        idx = min(range(len(xs)), key=lambda i: abs(xs[i] - x_tr))
        return {"x": xs[idx], "y": ys[idx]}

    ux, uy = offset_surface(bl_data["upper"], "upper")
    lx, ly = offset_surface(bl_data["lower"], "lower")
    tr_u = surface_point_at_x(bl_data["upper"], bl_data.get("transition_upper_x"))
    tr_l = surface_point_at_x(bl_data["lower"], bl_data.get("transition_lower_x"))
    return {"x": ux, "y": uy}, {"x": lx, "y": ly}, tr_u, tr_l


def build_flow_animation(sl_x, sl_y, speed_grid, x_arr, y_arr, coords, alpha_deg, show_particles=True, show_streamlines=True, bl_overlay=None, show_bl=True):
    """
    layout.images[0] : permanent PNG background (heatmap + airfoil fill)
    Trace 0 : streamlines (static)
    Trace 1 : airfoil outline (static)
    Trace 2 : white particles (animated — only trace updated in frames)
    Trace 3 : invisible colorbar dummy
    """
    airfoil_x = [p[0] for p in coords] + [coords[0][0]]
    airfoil_y = [p[1] for p in coords] + [coords[0][1]]

    plot_xmin = min(airfoil_x) - 0.4
    plot_xmax = max(airfoil_x) + 0.4
    plot_ymin = min(airfoil_y) - 0.55
    plot_ymax = max(airfoil_y) + 0.55

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

    trace_airfoil = go.Scatter(
        x=airfoil_x, y=airfoil_y,
        mode="lines",
        line=dict(color="#a5b4fc", width=1.5),
        fill="toself",
        fillcolor="rgba(15,23,42,1.0)",
        hoverinfo="skip", showlegend=False
    )

    bl_traces = []
    if bl_overlay is not None and show_bl:
        upper_env, lower_env, tr_upper, tr_lower = bl_overlay
        bl_traces.append(go.Scatter(
            x=upper_env["x"], y=upper_env["y"], mode="lines",
            line=dict(color="rgba(251,191,36,0.9)", width=1.5, dash="dash"),
            hoverinfo="skip", showlegend=False,
        ))
        bl_traces.append(go.Scatter(
            x=lower_env["x"], y=lower_env["y"], mode="lines",
            line=dict(color="rgba(251,191,36,0.9)", width=1.5, dash="dash"),
            hoverinfo="skip", showlegend=False,
        ))
        if tr_upper is not None:
            bl_traces.append(go.Scatter(
                x=[tr_upper["x"]], y=[tr_upper["y"]], mode="markers+text",
                marker=dict(symbol="triangle-up", size=10, color="rgba(251,191,36,1.0)",
                            line=dict(color="white", width=1)),
                text=["T"], textposition="top center",
                textfont=dict(color="rgba(251,191,36,1.0)", size=10),
                hovertemplate=f"Upper transition x/c={tr_upper['x']:.3f}<extra></extra>",
                showlegend=False,
            ))
        if tr_lower is not None:
            bl_traces.append(go.Scatter(
                x=[tr_lower["x"]], y=[tr_lower["y"]], mode="markers+text",
                marker=dict(symbol="triangle-down", size=10, color="rgba(251,191,36,1.0)",
                            line=dict(color="white", width=1)),
                text=["T"], textposition="bottom center",
                textfont=dict(color="rgba(251,191,36,1.0)", size=10),
                hovertemplate=f"Lower transition x/c={tr_lower['x']:.3f}<extra></extra>",
                showlegend=False,
            ))

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

    particle_idx = 2 + len(bl_traces)
    dx0, dy0 = frame_dots[0]
    trace_particles = go.Scatter(
        x=dx0, y=dy0,
        mode="markers",
        marker=dict(size=5, color="white", opacity=0.9, line=dict(width=0)),
        hoverinfo="skip", showlegend=False,
        visible=show_particles,
    )

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
                tickvals=[0, 0.25, 0.50, 0.75, 1.0],
                ticktext=["0", "0.5×", "1.0×", "1.5×", "2.0×"],
                tickfont=dict(color="white"),
                thickness=12, len=0.6, x=1.02,
            )
        ),
        hoverinfo="skip", showlegend=False
    )

    frames = []
    for f in range(n_frames):
        fdx, fdy = frame_dots[f]
        frames.append(go.Frame(
            data=[go.Scatter(
                x=fdx, y=fdy,
                mode="markers",
                marker=dict(size=5, color="white", opacity=0.9, line=dict(width=0))
            )],
            traces=[particle_idx],
            name=str(f)
        ))

    fig = go.Figure(
        data=[trace_lines, trace_airfoil] + bl_traces + [trace_particles, trace_colorbar],
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
if 'show_bl' not in st.session_state:
    st.session_state.show_bl = True
if 'sweep_mode' not in st.session_state:
    st.session_state.sweep_mode = False
if 'sweep_results' not in st.session_state:
    st.session_state.sweep_results = None
if 'sweep_params' not in st.session_state:
    st.session_state.sweep_params = None
if 'batch_mode' not in st.session_state:
    st.session_state.batch_mode = False
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = None
if 'batch_params' not in st.session_state:
    st.session_state.batch_params = None

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

    sweep_mode = st.checkbox(
        "AOA Sweep",
        value=st.session_state.sweep_mode,
        help="Sweep through a range of angles and generate a polar table",
        disabled=st.session_state.batch_mode
    )
    if sweep_mode != st.session_state.sweep_mode:
        st.session_state.sweep_mode = sweep_mode
        st.rerun()

    if not st.session_state.sweep_mode:
        alpha = st.slider(
            "Angle of Attack",
            min_value=-20.0, max_value=20.0, value=5.0, step=0.5,
            help="Angle between chord line and freestream",
            label_visibility="collapsed"
        )
        st.caption(f"Selected: **{alpha}°**")
        alpha_start = alpha_end = alpha
        alpha_step = 1.0
    else:
        alpha = None
        st.caption("Select sweep range:")
        sweep_range = st.slider(
            "AOA Range",
            min_value=-20.0, max_value=20.0, value=(-5.0, 15.0), step=0.5,
            help="Start and end angle of attack",
            label_visibility="collapsed"
        )
        alpha_start, alpha_end = sweep_range
        st.caption(f"**{alpha_start}°** to **{alpha_end}°**")
        alpha_step = st.select_slider(
            "Step size",
            options=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
            value=1.0,
            help="Angle increment between each XFOIL run",
            label_visibility="collapsed"
        )
        st.caption(f"Step: **{alpha_step}°**")
        n_steps = int(round((alpha_end - alpha_start) / alpha_step)) + 1
        st.caption(f"Total runs: **{n_steps}**")

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

    # ── Upload mode toggle ────────────────────────────────────────────────
    batch_mode = st.checkbox(
        "📦 Batch Upload (up to 10 files)",
        value=st.session_state.batch_mode,
        help="Upload multiple airfoil files at once. AOA sweep and visualisations are disabled in batch mode."
    )
    if batch_mode != st.session_state.batch_mode:
        st.session_state.batch_mode = batch_mode
        st.rerun()

    if st.session_state.batch_mode:
        uploaded_files = st.file_uploader(
            "📁 Upload up to 10 Airfoil .dat Files",
            type="dat",
            accept_multiple_files=True,
            help="Upload up to 10 .dat files. Results shown as a table."
        )
        if uploaded_files and len(uploaded_files) > 10:
            st.warning("⚠️ Maximum 10 files allowed. Only the first 10 will be analysed.")
            uploaded_files = uploaded_files[:10]
        uploaded_file = None
        has_upload = bool(uploaded_files)
    else:
        uploaded_file = st.file_uploader(
            "📁 Upload Airfoil .dat File",
            type="dat",
            help="Upload a file with airfoil x,y coordinates"
        )
        uploaded_files = []
        has_upload = uploaded_file is not None

    if st.session_state.batch_mode:
        btn_label = "🚀 Run Batch Analysis"
    elif st.session_state.sweep_mode:
        btn_label = "🚀 Run Sweep"
    else:
        btn_label = "🚀 Run Analysis"

    run_analysis = st.button(btn_label, type="primary", disabled=not has_upload)

    if has_upload and run_analysis:
        backend_url = os.getenv("BACKEND_URL", BACKEND_URL)

        if 'analyzing' in st.session_state and st.session_state.analyzing:
            st.warning("⏳ Analysis already in progress. Please wait...")
            st.stop()

        st.session_state.analyzing = True

        try:
            if st.session_state.batch_mode:
                # ── Batch Analysis ────────────────────────────────────────
                files_to_run = uploaded_files[:10]
                batch_rows = []
                prog = st.progress(0, text="Starting batch analysis...")
                status_txt = st.empty()

                for i, f in enumerate(files_to_run):
                    pct = int((i / len(files_to_run)) * 100)
                    prog.progress(pct, text=f"Analysing {f.name}... ({pct}% complete, {i+1}/{len(files_to_run)} files)")
                    status_txt.caption(f"File {i+1} of {len(files_to_run)}: {f.name}")
                    try:
                        r = run_xfoil_analysis(
                            file_content=f.getvalue(),
                            filename=f.name,
                            reynolds=reynolds,
                            alpha=float(alpha) if not st.session_state.sweep_mode else 5.0,
                            backend_url=backend_url
                        )
                        coeffs = r.get("coefficients", {})
                        cl = coeffs.get("CL", None)
                        cd = coeffs.get("CD", None)
                        cm = coeffs.get("Cm", None)
                        ld = (cl / cd) if (cl is not None and cd and cd != 0) else None
                        batch_rows.append({
                            "Airfoil": f.name.replace(".dat", ""),
                            "CL": round(cl, 4) if cl is not None else "—",
                            "CD": round(cd, 5) if cd is not None else "—",
                            "L/D": round(ld, 2) if ld is not None else "—",
                            "Cm": round(cm, 4) if cm is not None else "—",
                            "Status": "✅ Converged"
                        })
                    except Exception:
                        batch_rows.append({
                            "Airfoil": f.name.replace(".dat", ""),
                            "CL": "—", "CD": "—", "L/D": "—", "Cm": "—",
                            "Status": "❌ Failed"
                        })

                prog.progress(100, text="✅ Batch complete!")
                status_txt.empty()

                st.session_state.batch_results = batch_rows
                st.session_state.batch_params = {
                    'reynolds': reynolds,
                    'alpha': alpha if not st.session_state.sweep_mode else 5.0,
                    'n_files': len(files_to_run)
                }
                st.session_state.results = None
                st.session_state.sweep_results = None
                st.session_state.analyzing = False

            else:
                file_content = uploaded_file.getvalue()

            if st.session_state.sweep_mode:
                # ── AOA Sweep ─────────────────────────────────────────────
                alphas = [round(alpha_start + i * alpha_step, 2)
                          for i in range(int(round((alpha_end - alpha_start) / alpha_step)) + 1)
                          if round(alpha_start + i * alpha_step, 2) <= alpha_end + 1e-9]

                sweep_rows = []
                prog = st.progress(0, text="Starting sweep...")
                status_txt = st.empty()

                for i, a in enumerate(alphas):
                    pct = int((i / len(alphas)) * 100)
                    prog.progress(pct, text=f"Running α = {a}°... ({pct}% complete, {i}/{len(alphas)} steps)")
                    status_txt.caption(f"Step {i+1} of {len(alphas)}: α = {a}°")
                    try:
                        r = run_xfoil_analysis(
                            file_content=file_content,
                            filename=uploaded_file.name,
                            reynolds=reynolds,
                            alpha=float(a),
                            backend_url=backend_url
                        )
                        coeffs = r.get("coefficients", {})
                        cl = coeffs.get("CL", None)
                        cd = coeffs.get("CD", None)
                        cm = coeffs.get("Cm", None)
                        ld = (cl / cd) if (cl is not None and cd and cd != 0) else None
                        sweep_rows.append({
                            "α (°)": a,
                            "CL": round(cl, 4) if cl is not None else "—",
                            "CD": round(cd, 5) if cd is not None else "—",
                            "L/D": round(ld, 2) if ld is not None else "—",
                            "Cm": round(cm, 4) if cm is not None else "—",
                            "Status": "✅ Converged"
                        })
                    except Exception as step_err:
                        sweep_rows.append({
                            "α (°)": a,
                            "CL": "—", "CD": "—", "L/D": "—", "Cm": "—",
                            "Status": f"❌ Failed"
                        })

                prog.progress(100, text="✅ Sweep complete!")
                status_txt.empty()

                # Store first converged result for geometry/parser display
                first_result = None
                for a in alphas:
                    try:
                        first_result = run_xfoil_analysis(
                            file_content=file_content,
                            filename=uploaded_file.name,
                            reynolds=reynolds,
                            alpha=float(a),
                            backend_url=backend_url
                        )
                        break
                    except Exception:
                        continue

                st.session_state.sweep_results = sweep_rows
                st.session_state.batch_results = None
                st.session_state.sweep_params = {
                    'reynolds': reynolds,
                    'alpha_start': alpha_start,
                    'alpha_end': alpha_end,
                    'alpha_step': alpha_step,
                    'filename': uploaded_file.name,
                    'first_result': first_result,
                }
                st.session_state.results = None
                st.session_state.analyzing = False

            elif not st.session_state.batch_mode:
                # ── Single-point analysis ─────────────────────────────────
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
                st.session_state.sweep_results = None
                st.session_state.batch_results = None
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

    # ── Batch Results ─────────────────────────────────────────────────────────
    if st.session_state.batch_results is not None:
        bp = st.session_state.batch_params
        st.markdown("---")
        st.info(
            f"📦 **Batch Analysis** | {bp['n_files']} files | "
            f"Re = {bp['reynolds']:,} | α = {bp['alpha']}°"
        )
        st.subheader("📋 Batch Results")

        batch_df = pd.DataFrame(st.session_state.batch_results)
        st.dataframe(batch_df, use_container_width=True, hide_index=True)

        csv_data = batch_df.to_csv(index=False)
        st.download_button(
            label="⬇️ Export as CSV",
            data=csv_data,
            file_name=f"aerolab_batch_Re{int(bp['reynolds'])}_alpha{bp['alpha']}.csv",
            mime="text/csv",
        )

    # ── Sweep Results ─────────────────────────────────────────────────────────
    if st.session_state.sweep_results is not None:
        sp = st.session_state.sweep_params
        st.markdown("---")
        st.info(
            f"📊 **{sp['filename']}** | Re = {sp['reynolds']:,} | "
            f"α = {sp['alpha_start']}° → {sp['alpha_end']}° (step {sp['alpha_step']}°)"
        )
        st.subheader("📋 AOA Sweep Results")

        sweep_df = pd.DataFrame(st.session_state.sweep_results)
        st.dataframe(sweep_df, use_container_width=True, hide_index=True)

        # CSV export
        csv_data = sweep_df.to_csv(index=False)
        st.download_button(
            label="⬇️ Export as CSV",
            data=csv_data,
            file_name=sp['filename'].replace(".dat", f"_sweep_Re{int(sp['reynolds'])}.csv"),
            mime="text/csv",
        )

        # Polar plots download
        converged = sweep_df[sweep_df["Status"] == "✅ Converged"].copy()
        if len(converged) >= 2:
            st.markdown("---")
            st.subheader("📈 Download Polar Plots")
            try:
                import io as _io
                import plotly.graph_objects as go
                import plotly.io as pio

                cl_vals = pd.to_numeric(converged["CL"], errors='coerce')
                cd_vals = pd.to_numeric(converged["CD"], errors='coerce')
                cm_vals = pd.to_numeric(converged["Cm"], errors='coerce')
                ld_vals = pd.to_numeric(converged["L/D"], errors='coerce')
                aoa_vals = converged["α (°)"]

                plots = {
                    "CL_vs_AOA": (aoa_vals, cl_vals, "α (°)", "CL", "CL vs Angle of Attack"),
                    "CD_vs_AOA": (aoa_vals, cd_vals, "α (°)", "CD", "CD vs Angle of Attack"),
                    "CM_vs_AOA": (aoa_vals, cm_vals, "α (°)", "Cm", "Cm vs Angle of Attack"),
                    "CL_vs_CD":  (cd_vals,  cl_vals, "CD",    "CL", "Drag Polar (CL vs CD)"),
                    "LD_vs_AOA": (aoa_vals, ld_vals, "α (°)", "L/D", "L/D vs Angle of Attack"),
                }

                dl_cols = st.columns(len(plots))
                for col, (name, (xd, yd, xl, yl, title)) in zip(dl_cols, plots.items()):
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=xd, y=yd, mode='lines+markers',
                        line=dict(color='#667eea', width=2),
                        marker=dict(size=6)
                    ))
                    fig.update_layout(
                        title=title, xaxis_title=xl, yaxis_title=yl,
                        plot_bgcolor='white', height=400, width=600,
                        font=dict(family="Arial", size=13),
                    )
                    fig.update_xaxes(showgrid=True, gridcolor='lightgray')
                    fig.update_yaxes(showgrid=True, gridcolor='lightgray')
                    img_bytes = pio.to_image(fig, format="png", scale=2)
                    with col:
                        st.download_button(
                            label=f"⬇️ {yl} vs {xl}",
                            data=img_bytes,
                            file_name=f"{sp['filename'].replace('.dat','')}_{name}.png",
                            mime="image/png",
                            key=f"dl_{name}"
                        )
            except Exception as plot_err:
                st.warning(f"Plot generation failed: {plot_err}")

        # Show airfoil geometry and parser output from first converged result
        if sp.get('first_result'):
            fr = sp['first_result']
            st.markdown("---")
            coords_after = pd.DataFrame(fr["coords_after"], columns=["x", "y"])
            st.subheader("🛩️ Airfoil Geometry")
            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(
                x=coords_after["x"], y=coords_after["y"],
                mode='lines', name='Airfoil',
                line=dict(color='#667eea', width=3),
                fill='toself', fillcolor='rgba(102, 126, 234, 0.2)',
            ))
            fig1.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.3)
            fig1.update_layout(
                title=sp['filename'], xaxis_title="x/c", yaxis_title="y/c",
                height=350, plot_bgcolor='white',
                yaxis=dict(scaleanchor="x", scaleratio=1)
            )
            st.plotly_chart(fig1, use_container_width=True)

            # Parser output box
            st.markdown("---")
            st.subheader("🔧 Parser Output")
            parser_fixes = fr.get("parser_fixes", [])
            if parser_fixes and parser_fixes != ["No changes made — file was already in valid Selig format"]:
                fix_lines = "\n".join(f"  ✔  {fix}" for fix in parser_fixes)
                fix_header = f"⚠️  {len(parser_fixes)} repair(s) applied:"
            else:
                fix_lines = "  ✔  No changes made — file was already in valid Selig format"
                fix_header = "✅ File accepted as-is:"
            st.markdown(
                f"""<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;
                padding:14px 18px 6px;font-family:'Courier New',Courier,monospace;
                font-size:13px;color:#8b949e;line-height:1.6;">
                <span style="color:#58a6ff;font-weight:600;">AeroLab Parser</span>
                <span style="color:#3fb950;"> &gt;</span>
                <span style="color:#e6edf3;"> {sp['filename']}</span><br>
                <span style="color:#f0883e;">{fix_header}</span><br>
                <span style="color:#3fb950;white-space:pre-wrap;">{fix_lines}</span>
                </div>""",
                unsafe_allow_html=True
            )

            coord_lines_sweep = "\n".join(
                f"  {x:.6f}  {y:.6f}"
                for x, y in fr["coords_after"]
            )
            coord_text_sweep = f"AIRFOIL\n{coord_lines_sweep}"
            with st.expander("📄 View Parsed Coordinates", expanded=False):
                st.code(coord_text_sweep, language=None)
                st.download_button(
                    label="⬇️ Download parsed .dat",
                    data=coord_text_sweep,
                    file_name=sp['filename'].replace(".dat", "_parsed.dat"),
                    mime="text/plain",
                    key="sweep_parsed_download"
                )
            st.markdown("---")
            st.subheader("🌊 Interactive Wind Tunnel")
            st.caption(
                "Live Lattice-Boltzmann (D2Q9) simulation of your airfoil. "
                "Adjust AOA, flow speed, and trail density with the sliders. "
                "Use 📷 Save PNG to capture the current view. "
                "Note: Reynolds number shown is in lattice units — independent of the XFOIL analysis above."
            )
            _sweep_name = sp['filename'].replace(".dat", "").replace("_", " ")
            build_lbm_component(
                coords_after=fr["coords_after"],
                airfoil_name=_sweep_name,
            )
            with st.expander("ℹ️ About This Visualisation"):
                st.markdown("""
                **Interactive Wind Tunnel — D2Q9 Lattice-Boltzmann Method (WebGL2)**
                - **Colour field** — fluid speed: blue = slow, red = fast
                - **White trails** — passive smoke tracers showing flow direction
                - **AOA slider** — pitches the airfoil in real time
                - **📷 Save PNG** — captures the current canvas as a PNG file
                """)

    # ── Results ───────────────────────────────────────────────────────────────
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

        # ── Parsed Coordinate Box ─────────────────────────────────────────────
        st.markdown("---")
        st.subheader("🔧 Parser Output")

        # Fix log
        parser_fixes = result.get("parser_fixes", [])
        if parser_fixes and parser_fixes != ["No changes made — file was already in valid Selig format"]:
            fix_lines = "\n".join(f"  ✔  {fix}" for fix in parser_fixes)
            fix_header = f"⚠️  {len(parser_fixes)} repair(s) applied:"
        else:
            fix_lines = "  ✔  No changes made — file was already in valid Selig format"
            fix_header = "✅ File accepted as-is:"

        st.markdown(
            f"""
            <div style="
                background:#0d1117;
                border:1px solid #30363d;
                border-radius:8px;
                padding:14px 18px 6px;
                margin-bottom:8px;
                font-family:'Courier New',Courier,monospace;
                font-size:13px;
                color:#8b949e;
                line-height:1.6;
            ">
                <span style="color:#58a6ff;font-weight:600;">AeroLab Parser</span>
                <span style="color:#3fb950;"> &gt;</span>
                <span style="color:#e6edf3;"> {last_params['filename']}</span><br>
                <span style="color:#f0883e;">{fix_header}</span><br>
                <span style="color:#3fb950;white-space:pre-wrap;">{fix_lines}</span>
            </div>
            """,
            unsafe_allow_html=True
        )

        # Coordinate output
        coord_lines = "\n".join(
            f"  {x:.6f}  {y:.6f}"
            for x, y in result["coords_after"]
        )
        coord_text = f"AIRFOIL\n{coord_lines}"

        with st.expander("📄 View Parsed Coordinates", expanded=False):
            st.code(coord_text, language=None)
            st.download_button(
                label="⬇️ Download parsed .dat",
                data=coord_text,
                file_name=last_params['filename'].replace(".dat", "_parsed.dat"),
                mime="text/plain",
            )

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

        # ── Airflow Visualization (LBM Wind Tunnel) ─────────────────────────
        st.markdown("---")
        st.subheader("🌊 Interactive Wind Tunnel")
        st.caption(
            "Live Lattice-Boltzmann (D2Q9) simulation of your airfoil. "
            "Adjust AOA, flow speed, and trail density with the sliders. "
            "Use 📷 Save PNG to capture the current view. "
            "Note: Reynolds number shown is in lattice units — independent of the XFOIL analysis above."
        )

        _airfoil_display_name = (
            uploaded_file.name.replace(".dat", "").replace("_", " ")
            if uploaded_file is not None
            else "Airfoil"
        )

        build_lbm_component(
            coords_after=result["coords_after"],
            airfoil_name=_airfoil_display_name,
        )

        with st.expander("ℹ️ About This Visualisation"):
            st.markdown("""
            **Interactive Wind Tunnel — D2Q9 Lattice-Boltzmann Method (WebGL2)**

            - **Colour field** — fluid speed: blue = slow (high pressure), red = fast (low pressure)
            - **White trails** — passive smoke tracers showing flow direction and speed
            - **AOA slider** — pitches the airfoil in real time; freestream stays horizontal
            - **Field selector** — switch between velocity magnitude, pressure (Cp), and vorticity
            - **Vorticity view** — red = clockwise rotation, blue = counter-clockwise; shows wake vortex shedding
            - **📷 Save PNG** — captures the current canvas state as a PNG file

            *Qualitative visualisation using your uploaded airfoil geometry.
            Captures correct flow topology (stagnation point, separation, wake vortices)
            but runs at low lattice Reynolds number — not the physical Re from the XFOIL analysis.*
            """)

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