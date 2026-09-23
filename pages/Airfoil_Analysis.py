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
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_utils import increment_analysis_count
from aerolab_theme import COLORS, CMAP_GRADIENT, inject_theme, cmap_bar, eyebrow


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

    components.html(html, height=700, scrolling=False)


# ── Dual LBM Wind Tunnel component (Compare mode) ───────────────────────────
_LBM_DUAL_TEMPLATE = os.path.join(os.path.dirname(__file__), "airfoil_flow_lbm_dual_aerolab.html")

def build_lbm_dual_component(coords_a, name_a: str, coords_b, name_b: str) -> None:
    """
    Render two independent LBM wind-tunnel simulations side by side, driven
    by one shared control panel (angle of attack, field mode, flow speed,
    trails). Used by Compare mode. Each airfoil gets its own canvas and
    stat cards (CL/CD/Re/Separation differ per airfoil); AoA and the other
    flow parameters are shared since both listeners attach to the same
    control elements.
    """
    try:
        with open(_LBM_DUAL_TEMPLATE, "r") as f:
            template = f.read()
    except FileNotFoundError:
        st.error(
            f"⚠️ Dual LBM visualisation template not found. Expected: `{_LBM_DUAL_TEMPLATE}`"
        )
        return

    def _coords_json(coords):
        return json.dumps([[round(float(x), 6), round(float(y), 6)] for x, y in coords])

    html = template
    html = html.replace("%%USER_COORDS_A%%", _coords_json(coords_a))
    html = html.replace("%%USER_NAME_A%%", json.dumps(name_a or "Airfoil A"))
    html = html.replace("%%USER_COORDS_B%%", _coords_json(coords_b))
    html = html.replace("%%USER_NAME_B%%", json.dumps(name_b or "Airfoil B"))

    components.html(html, height=760, scrolling=False)


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

inject_theme()
st.markdown(f"""
    <style>
        .param-label {{
            font-size: 0.82rem;
            font-weight: 600;
            color: {COLORS['text_faint']};
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.2rem;
        }}
        .panel-title {{
            font-family: 'Space Grotesk', sans-serif;
            font-size: 1.15rem;
            font-weight: 600;
            color: {COLORS['text']};
            padding-bottom: 0.6rem;
            border-bottom: 2px solid {COLORS['border']};
            margin-bottom: 1rem;
        }}
        .main-header {{
            font-family: 'Space Grotesk', sans-serif;
            font-size: 2.8rem;
            font-weight: 600;
            color: {COLORS['text']};
            margin-bottom: 0.2rem;
        }}
        .sub-header {{
            color: {COLORS['text_dim']};
            margin-bottom: 1.5rem;
            font-size: 1rem;
        }}
    </style>
""", unsafe_allow_html=True)

# ── Example Airfoils (bundled, no upload required) ──────────────────────────
EXAMPLE_AIRFOILS_DIR = os.path.join(os.path.dirname(__file__), "example_airfoils")
EXAMPLE_AIRFOILS = {
    "NACA 0012":  "naca0012.dat",
    "NACA 4412":  "naca4412.dat",
    "Clark Y":    "clarky.dat",
    "S1223":      "s1223.dat",
    "Eppler 387": "e387.dat",
}
NO_EXAMPLE_LABEL = "— Upload my own —"

@st.cache_data(show_spinner=False)
def load_example_airfoil(filename: str) -> bytes:
    with open(os.path.join(EXAMPLE_AIRFOILS_DIR, filename), "rb") as f:
        return f.read()

class _PresetFile:
    """Minimal stand-in for Streamlit's UploadedFile so example airfoils can
    flow through the exact same .name / .getvalue() call sites as a real
    upload, with no changes needed downstream."""
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content
    def getvalue(self) -> bytes:
        return self._content

def example_airfoil_picker(key: str):
    """Renders a small selectbox of bundled example airfoils. Returns a
    _PresetFile if one is chosen, or None if the user wants to upload their
    own (in which case the caller should render its own file_uploader)."""
    choice = st.selectbox(
        "Or choose an example airfoil",
        [NO_EXAMPLE_LABEL] + list(EXAMPLE_AIRFOILS.keys()),
        key=key,
        label_visibility="collapsed"
    )
    if choice == NO_EXAMPLE_LABEL:
        return None
    filename = EXAMPLE_AIRFOILS[choice]
    try:
        return _PresetFile(filename, load_example_airfoil(filename))
    except FileNotFoundError:
        st.error(f"⚠️ Example airfoil file not found: `{filename}`")
        return None

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
if 'ncrit' not in st.session_state:
    st.session_state.ncrit = 9.0
if 'analysis_mode' not in st.session_state:
    st.session_state.analysis_mode = "viscous"
if 'compare_mode' not in st.session_state:
    st.session_state.compare_mode = False
if 'compare_results' not in st.session_state:
    st.session_state.compare_results = None
if 'compare_params' not in st.session_state:
    st.session_state.compare_params = None

@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def run_xfoil_analysis(file_content: bytes, filename: str, reynolds: float, alpha: float, backend_url: str,
                        ncrit: float = 9.0, mode: str = "viscous", mach: float = 0.0):
    url = f"{backend_url}/upload_airfoil/"
    files = {"file": (filename, file_content, "text/plain")}
    data = {"reynolds": reynolds, "alpha": alpha, "ncrit": ncrit, "mode": mode, "mach": mach}
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

    st.markdown('<p class="param-label">Mach Number</p>', unsafe_allow_html=True)
    mach = st.slider(
        "Mach Number",
        min_value=0.0, max_value=0.75, value=0.0, step=0.05,
        help="Freestream Mach number. Applies XFOIL's Karman-Tsien compressibility "
             "correction. Default (0.0) matches incompressible flow, valid for most "
             "low-speed cases. The correction becomes unreliable above ~0.75 as shock "
             "effects appear, which this panel-method solver cannot capture.",
        label_visibility="collapsed"
    )
    st.caption(f"Mach: **{mach}**" + ("  (incompressible)" if mach == 0.0 else ""))

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown('<p class="param-label">Angle of Attack</p>', unsafe_allow_html=True)

    sweep_mode = st.checkbox(
        "AOA Sweep",
        value=st.session_state.sweep_mode,
        help="Sweep through a range of angles and generate a polar table",
        disabled=st.session_state.batch_mode or st.session_state.compare_mode
    )
    if sweep_mode != st.session_state.sweep_mode:
        st.session_state.sweep_mode = sweep_mode
        st.rerun()

    if not st.session_state.sweep_mode:
        alpha = st.slider(
            "Angle of Attack",
            min_value=-10.0, max_value=20.0, value=5.0, step=0.5,
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
            min_value=-10.0, max_value=20.0, value=(-5.0, 15.0), step=0.5,
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

    st.markdown('<p class="param-label">Analysis Mode</p>', unsafe_allow_html=True)
    analysis_mode = st.radio(
        "Analysis Mode",
        options=["viscous", "inviscid"],
        format_func=lambda m: "Viscous (recommended)" if m == "viscous" else "Inviscid (fast, less accurate)",
        index=0 if st.session_state.analysis_mode == "viscous" else 1,
        help="Viscous mode solves the boundary layer (accurate CD, BL data). "
             "Inviscid skips it — much faster but CD is unrealistically low and no BL data is returned.",
        label_visibility="collapsed"
    )
    st.session_state.analysis_mode = analysis_mode

    if analysis_mode == "viscous":
        ncrit = st.slider(
            "NCrit (transition criterion)",
            min_value=0.1, max_value=14.0, value=st.session_state.ncrit, step=0.1,
            help="Critical amplification factor for the e^N transition model. "
                 "Lower NCrit (~4-6) = more turbulent/noisy environment (e.g. wind tunnel with grid). "
                 "Higher NCrit (~9-11) = smoother/cleaner flow (e.g. sailplane in free air). Default: 9.0"
        )
        st.session_state.ncrit = ncrit
        st.caption(f"NCrit: **{ncrit}**")
    else:
        ncrit = st.session_state.ncrit
        st.caption("NCrit not used in inviscid mode")

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
        These are available directly from the **"Or choose an example airfoil"**
        dropdown above the upload box — no download needed:

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
        help="Upload multiple airfoil files at once. AOA sweep and visualisations are disabled in batch mode.",
        disabled=st.session_state.compare_mode
    )
    if batch_mode != st.session_state.batch_mode:
        st.session_state.batch_mode = batch_mode
        st.rerun()

    compare_mode = st.checkbox(
        "⚖️ Compare Two Airfoils",
        value=st.session_state.compare_mode,
        help="Run two airfoils side by side at the same Re/α/NCrit — numeric results, geometry, "
             "Cp, and a shared wind tunnel. Batch upload and AOA sweep are disabled in this mode.",
        disabled=st.session_state.batch_mode
    )
    if compare_mode != st.session_state.compare_mode:
        st.session_state.compare_mode = compare_mode
        if compare_mode:
            st.session_state.sweep_mode = False
        st.rerun()

    if st.session_state.compare_mode:
        cmp_col_a, cmp_col_b = st.columns(2)
        with cmp_col_a:
            preset_a = example_airfoil_picker(key="example_picker_a")
            if preset_a is not None:
                uploaded_file_a = preset_a
                st.caption(f"📄 Using example: **{preset_a.name}**")
            else:
                uploaded_file_a = st.file_uploader(
                    "📁 Airfoil A",
                    type=["dat", "txt"],
                    key="compare_upload_a",
                    help="First airfoil .dat or .txt file"
                )
        with cmp_col_b:
            preset_b = example_airfoil_picker(key="example_picker_b")
            if preset_b is not None:
                uploaded_file_b = preset_b
                st.caption(f"📄 Using example: **{preset_b.name}**")
            else:
                uploaded_file_b = st.file_uploader(
                    "📁 Airfoil B",
                    type=["dat", "txt"],
                    key="compare_upload_b",
                    help="Second airfoil .dat or .txt file"
                )
        uploaded_file = None
        uploaded_files = []
        has_upload = uploaded_file_a is not None and uploaded_file_b is not None
    elif st.session_state.batch_mode:
        uploaded_files = st.file_uploader(
            "📁 Upload up to 10 Airfoil .dat Files",
            type=["dat", "txt"],
            accept_multiple_files=True,
            help="Upload up to 10 .dat files. Results shown as a table."
        )
        if uploaded_files and len(uploaded_files) > 10:
            st.warning("⚠️ Maximum 10 files allowed. Only the first 10 will be analysed.")
            uploaded_files = uploaded_files[:10]
        uploaded_file = None
        has_upload = bool(uploaded_files)
    else:
        preset_single = example_airfoil_picker(key="example_picker_single")
        if preset_single is not None:
            uploaded_file = preset_single
            st.caption(f"📄 Using example: **{preset_single.name}**")
        else:
            uploaded_file = st.file_uploader(
                "📁 Upload Airfoil .dat File",
                type=["dat", "txt"],
                help="Upload a file with airfoil x,y coordinates"
            )
        uploaded_files = []
        has_upload = uploaded_file is not None

    if st.session_state.compare_mode:
        btn_label = "🚀 Run Comparison"
    elif st.session_state.batch_mode:
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
            if st.session_state.compare_mode:
                with st.spinner(f"🔄 Analyzing {uploaded_file_a.name} and {uploaded_file_b.name}..."):
                    result_a = run_xfoil_analysis(
                        file_content=uploaded_file_a.getvalue(),
                        filename=uploaded_file_a.name,
                        reynolds=reynolds,
                        alpha=alpha,
                        backend_url=backend_url,
                        ncrit=ncrit,
                        mode=analysis_mode,
                        mach=mach
                    )
                    result_b = run_xfoil_analysis(
                        file_content=uploaded_file_b.getvalue(),
                        filename=uploaded_file_b.name,
                        reynolds=reynolds,
                        alpha=alpha,
                        backend_url=backend_url,
                        ncrit=ncrit,
                        mode=analysis_mode,
                        mach=mach
                    )

                new_count = increment_analysis_count()
                if new_count:
                    st.toast(f"✅ Analysis #{new_count:,} completed!", icon="🎉")

                st.session_state.compare_results = {"A": result_a, "B": result_b}
                st.session_state.compare_params = {
                    'reynolds': reynolds,
                    'alpha': alpha,
                    'ncrit': ncrit,
                    'mode': analysis_mode,
                    'filename_a': uploaded_file_a.name,
                    'filename_b': uploaded_file_b.name,
                }
                st.session_state.results = None
                st.session_state.sweep_results = None
                st.session_state.batch_results = None
                st.session_state.analyzing = False
                st.success("✅ Comparison completed successfully!")

            elif st.session_state.batch_mode:
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
                            backend_url=backend_url,
                            ncrit=ncrit,
                            mode=analysis_mode,
                            mach=mach
                        )
                        coeffs = r.get("coefficients", {})
                        cl = coeffs.get("CL", None)
                        cd = coeffs.get("CD", None)
                        cm = coeffs.get("Cm", None)
                        ld = (cl / cd) if (cl is not None and cd and cd != 0) else None
                        fell_back = analysis_mode == "viscous" and coeffs.get("mode") == "inviscid"
                        batch_rows.append({
                            "Airfoil": f.name.replace(".dat", ""),
                            "CL": round(cl, 4) if cl is not None else "—",
                            "CD": round(cd, 5) if cd is not None else "—",
                            "L/D": round(ld, 2) if ld is not None else "—",
                            "Cm": round(cm, 4) if cm is not None else "—",
                            "Status": "⚠️ Fallback (Inviscid)" if fell_back else "✅ Converged"
                        })
                    except Exception:
                        batch_rows.append({
                            "Airfoil": f.name.replace(".dat", ""),
                            "CL": "—", "CD": "—", "L/D": "—", "Cm": "—",
                            "Status": "❌ Failed"
                        })

                prog.progress(100, text="✅ Batch complete!")
                status_txt.empty()

                n_converged_batch = sum(1 for r in batch_rows if r["Status"] != "❌ Failed")
                if n_converged_batch > 0:
                    for _ in range(n_converged_batch):
                        new_count = increment_analysis_count()
                    if new_count:
                        st.toast(f"✅ {n_converged_batch} analyses completed! (Total: #{new_count:,})", icon="🎉")

                st.session_state.batch_results = batch_rows
                st.session_state.batch_params = {
                    'reynolds': reynolds,
                    'alpha': alpha if not st.session_state.sweep_mode else 5.0,
                    'n_files': len(files_to_run),
                    'ncrit': ncrit,
                    'mode': analysis_mode,
                }
                st.session_state.results = None
                st.session_state.sweep_results = None
                st.session_state.compare_results = None
                st.session_state.analyzing = False

            else:
                file_content = uploaded_file.getvalue()

            if st.session_state.compare_mode:
                pass  # already fully handled above, nothing more to do

            elif st.session_state.sweep_mode:
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
                            backend_url=backend_url,
                            ncrit=ncrit,
                            mode=analysis_mode,
                            mach=mach
                        )
                        coeffs = r.get("coefficients", {})
                        cl = coeffs.get("CL", None)
                        cd = coeffs.get("CD", None)
                        cm = coeffs.get("Cm", None)
                        ld = (cl / cd) if (cl is not None and cd and cd != 0) else None
                        fell_back = analysis_mode == "viscous" and coeffs.get("mode") == "inviscid"
                        sweep_rows.append({
                            "α (°)": a,
                            "CL": round(cl, 4) if cl is not None else "—",
                            "CD": round(cd, 5) if cd is not None else "—",
                            "L/D": round(ld, 2) if ld is not None else "—",
                            "Cm": round(cm, 4) if cm is not None else "—",
                            "Status": "⚠️ Fallback (Inviscid)" if fell_back else "✅ Converged"
                        })
                    except Exception as step_err:
                        sweep_rows.append({
                            "α (°)": a,
                            "CL": "—", "CD": "—", "L/D": "—", "Cm": "—",
                            "Status": f"❌ Failed"
                        })

                prog.progress(100, text="✅ Sweep complete!")
                status_txt.empty()

                n_converged_sweep = sum(1 for r in sweep_rows if r["Status"] != "❌ Failed")
                if n_converged_sweep > 0:
                    for _ in range(n_converged_sweep):
                        new_count = increment_analysis_count()
                    if new_count:
                        st.toast(f"✅ {n_converged_sweep} sweep steps completed! (Total: #{new_count:,})", icon="🎉")

                # Store first converged result for geometry/parser display
                first_result = None
                for a in alphas:
                    try:
                        first_result = run_xfoil_analysis(
                            file_content=file_content,
                            filename=uploaded_file.name,
                            reynolds=reynolds,
                            alpha=float(a),
                            backend_url=backend_url,
                            ncrit=ncrit,
                            mode=analysis_mode,
                            mach=mach
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
                    'ncrit': ncrit,
                    'mode': analysis_mode,
                }
                st.session_state.results = None
                st.session_state.compare_results = None
                st.session_state.analyzing = False

            elif not st.session_state.batch_mode:
                # ── Single-point analysis ─────────────────────────────────
                with st.spinner("Computing... (30-60s on free tier, instant if cached)"):
                    result = run_xfoil_analysis(
                        file_content=file_content,
                        filename=uploaded_file.name,
                        reynolds=reynolds,
                        alpha=alpha,
                        backend_url=backend_url,
                        ncrit=ncrit,
                        mode=analysis_mode,
                        mach=mach
                    )

                new_count = increment_analysis_count()
                if new_count:
                    st.toast(f"✅ Analysis #{new_count:,} completed!", icon="🎉")

                st.session_state.results = result
                st.session_state.last_params = {
                    'reynolds': reynolds,
                    'alpha': alpha,
                    'filename': uploaded_file.name,
                    'ncrit': ncrit,
                    'mode': analysis_mode
                }
                st.session_state.sweep_results = None
                st.session_state.batch_results = None
                st.session_state.compare_results = None
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

    # ── Compare Results ──────────────────────────────────────────────────────
    if st.session_state.compare_results is not None:
        cp = st.session_state.compare_params
        res_a = st.session_state.compare_results["A"]
        res_b = st.session_state.compare_results["B"]
        st.markdown("---")

        cmp_mode_requested = cp.get('mode', 'viscous')
        cmp_mode_str = (f"Viscous (NCrit={cp['ncrit']})" if cmp_mode_requested == "viscous"
                         else cmp_mode_requested.capitalize())
        st.info(
            f"⚖️ **Comparing** {cp['filename_a']} vs {cp['filename_b']} | "
            f"Re = {cp['reynolds']:,} | α = {cp['alpha']}° | {cmp_mode_str}"
        )

        fallback_names = []
        for name, res in [(cp['filename_a'], res_a), (cp['filename_b'], res_b)]:
            actual_mode = res.get("coefficients", {}).get("mode", cmp_mode_requested)
            if cmp_mode_requested == "viscous" and actual_mode == "inviscid":
                fallback_names.append(name)
        if fallback_names:
            st.warning(
                f"⚠️ **{', '.join(fallback_names)}** didn't converge viscous and fell back to inviscid "
                "(CD = 0 for that airfoil) — try a different Re, α, or NCrit."
            )

        st.subheader("📋 Comparison")

        def _cmp_metrics(coeffs):
            cl, cd, cm = coeffs.get("CL"), coeffs.get("CD"), coeffs.get("Cm")
            ld = (cl / cd) if (cl is not None and cd not in (None, 0)) else None
            return cl, cd, cm, ld

        coeffs_a, coeffs_b = res_a.get("coefficients", {}), res_b.get("coefficients", {})
        cl_a, cd_a, cm_a, ld_a = _cmp_metrics(coeffs_a)
        cl_b, cd_b, cm_b, ld_b = _cmp_metrics(coeffs_b)

        cmp_col_a, cmp_col_b = st.columns(2)
        for col, name, cl, cd, cm, ld in [
            (cmp_col_a, cp['filename_a'], cl_a, cd_a, cm_a, ld_a),
            (cmp_col_b, cp['filename_b'], cl_b, cd_b, cm_b, ld_b),
        ]:
            with col:
                st.markdown(f"**{name.replace('.dat', '')}**")
                m1, m2 = st.columns(2)
                m1.metric("CL", f"{cl:.4f}" if cl is not None else "N/A")
                m2.metric("CD", f"{cd:.5f}" if cd is not None else "N/A")
                m3, m4 = st.columns(2)
                if cd == 0:
                    m3.metric("L/D", "∞", help="Inviscid: CD = 0, L/D undefined")
                elif ld is not None:
                    m3.metric("L/D", f"{ld:.2f}")
                else:
                    m3.metric("L/D", "N/A")
                m4.metric("Cm", f"{cm:.4f}" if cm is not None else "N/A")

        st.markdown("---")

        geom_col_a, geom_col_b = st.columns(2)
        for col, name, res in [(geom_col_a, cp['filename_a'], res_a), (geom_col_b, cp['filename_b'], res_b)]:
            with col:
                coords_df = pd.DataFrame(res["coords_after"], columns=["x", "y"])
                fig_geom = go.Figure()
                fig_geom.add_trace(go.Scatter(
                    x=coords_df["x"], y=coords_df["y"], mode='lines', name=name,
                    line=dict(color=COLORS['c2'], width=3),
                    fill='toself', fillcolor='rgba(0, 255, 255, 0.15)',
                    hovertemplate='x: %{x:.4f}<br>y: %{y:.4f}<extra></extra>'
                ))
                fig_geom.add_hline(y=0, line_dash="dash", line_color=COLORS['border_strong'], opacity=0.3)
                fig_geom.add_vline(x=0, line_dash="dash", line_color=COLORS['border_strong'], opacity=0.3)
                fig_geom.update_layout(
                    title=name, xaxis_title="x/c", yaxis_title="y/c",
                    height=320, hovermode='closest', plot_bgcolor=COLORS['bg_card'],
                    paper_bgcolor=COLORS['bg_card'], font=dict(color=COLORS['text_dim']),
                    yaxis=dict(scaleanchor="x", scaleratio=1),
                    margin=dict(t=40, b=20)
                )
                fig_geom.update_xaxes(showgrid=True, gridcolor=COLORS['border'])
                fig_geom.update_yaxes(showgrid=True, gridcolor=COLORS['border'])
                st.plotly_chart(fig_geom, use_container_width=True, key=f"cmp_geom_{name}")

                if res["cp_x"] and res["cp_values"]:
                    cp_x_arr, cp_val_arr = np.array(res["cp_x"]), np.array(res["cp_values"])
                    mid_idx = len(cp_x_arr) // 2
                    fig_cp = go.Figure()
                    fig_cp.add_trace(go.Scatter(
                        x=cp_x_arr[:mid_idx], y=cp_val_arr[:mid_idx], mode='lines',
                        name='Upper surface', line=dict(color=COLORS['c2'], width=3)
                    ))
                    fig_cp.add_trace(go.Scatter(
                        x=cp_x_arr[mid_idx:], y=cp_val_arr[mid_idx:], mode='lines',
                        name='Lower surface', line=dict(color=COLORS['c6'], width=3)
                    ))
                    fig_cp.add_hline(y=0, line_dash="dash", line_color=COLORS['border_strong'], opacity=0.3)
                    fig_cp.update_layout(
                        xaxis_title="x/c", yaxis_title="Cp",
                        height=320, hovermode='closest', plot_bgcolor=COLORS['bg_card'],
                        paper_bgcolor=COLORS['bg_card'], font=dict(color=COLORS['text_dim']),
                        yaxis=dict(autorange='reversed'),
                        margin=dict(t=20, b=20)
                    )
                    fig_cp.update_xaxes(showgrid=True, gridcolor=COLORS['border'])
                    fig_cp.update_yaxes(showgrid=True, gridcolor=COLORS['border'])
                    st.plotly_chart(fig_cp, use_container_width=True, key=f"cmp_cp_{name}")
                else:
                    st.caption("ℹ️ No Cp data available")

        st.markdown("---")
        st.subheader("🌊 Interactive Wind Tunnel — Side by Side")
        build_lbm_dual_component(
            coords_a=res_a["coords_after"], name_a=cp['filename_a'],
            coords_b=res_b["coords_after"], name_b=cp['filename_b'],
        )

    # ── Batch Results ─────────────────────────────────────────────────────────
    if st.session_state.batch_results is not None:
        bp = st.session_state.batch_params
        st.markdown("---")
        bp_mode = bp.get('mode', 'viscous')
        bp_mode_str = f"Viscous (NCrit={bp['ncrit']})" if bp_mode == "viscous" and 'ncrit' in bp else bp_mode.capitalize()
        st.info(
            f"📦 **Batch Analysis** | {bp['n_files']} files | "
            f"Re = {bp['reynolds']:,} | α = {bp['alpha']}° | {bp_mode_str}"
        )
        _n_fallback_batch = sum(1 for r in st.session_state.batch_results if r.get("Status") == "⚠️ Fallback (Inviscid)")
        if _n_fallback_batch:
            st.warning(
                f"⚠️ **{_n_fallback_batch} file(s) didn't converge viscous** and fell back to inviscid "
                "(CD = 0 for those rows) — see the Status column below."
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
        sp_mode = sp.get('mode', 'viscous')
        sp_mode_str = f"Viscous (NCrit={sp['ncrit']})" if sp_mode == "viscous" and 'ncrit' in sp else sp_mode.capitalize()
        st.info(
            f"📊 **{sp['filename']}** | Re = {sp['reynolds']:,} | "
            f"α = {sp['alpha_start']}° → {sp['alpha_end']}° (step {sp['alpha_step']}°) | {sp_mode_str}"
        )
        _n_fallback = sum(1 for r in st.session_state.sweep_results if r.get("Status") == "⚠️ Fallback (Inviscid)")
        if _n_fallback:
            st.warning(
                f"⚠️ **{_n_fallback} point(s) in this sweep didn't converge viscous** and fell back to "
                "inviscid (CD = 0 for those points) — see the Status column below. "
                "They're excluded from the drag-polar and L/D plots since CD = 0 isn't physically meaningful."
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
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt

                cl_vals = pd.to_numeric(converged["CL"], errors='coerce')
                cd_vals = pd.to_numeric(converged["CD"], errors='coerce')
                cm_vals = pd.to_numeric(converged["Cm"], errors='coerce')
                ld_vals = pd.to_numeric(converged["L/D"], errors='coerce')
                aoa_vals = converged["α (°)"]

                plots = {
                    "CL_vs_AOA": (aoa_vals, cl_vals, "Angle of Attack α (°)", "Lift Coefficient CL", "CL vs Angle of Attack", "⬇️ CL vs α"),
                    "CD_vs_AOA": (aoa_vals, cd_vals, "Angle of Attack α (°)", "Drag Coefficient CD", "CD vs Angle of Attack", "⬇️ CD vs α"),
                    "CM_vs_AOA": (aoa_vals, cm_vals, "Angle of Attack α (°)", "Pitching Moment Cm", "Cm vs Angle of Attack", "⬇️ Cm vs α"),
                    "CL_vs_CD":  (cd_vals,  cl_vals, "Drag Coefficient CD",   "Lift Coefficient CL", "Drag Polar", "⬇️ Drag Polar"),
                    "LD_vs_AOA": (aoa_vals, ld_vals, "Angle of Attack α (°)", "Lift-to-Drag Ratio L/D", "L/D vs Angle of Attack", "⬇️ L/D vs α"),
                }

                dl_cols = st.columns(len(plots))
                airfoil_label = sp['filename'].replace(".dat", "")

                for col, (name, (xd, yd, xl, yl, title, btn_label)) in zip(dl_cols, plots.items()):
                    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
                    ax.plot(xd, yd, color='#667eea', linewidth=2,
                            marker='o', markersize=4, markerfacecolor='#667eea')
                    ax.set_xlabel(xl, fontsize=11)
                    ax.set_ylabel(yl, fontsize=11)
                    ax.set_title(f"{title}\n{airfoil_label} | Re = {sp['reynolds']:,}", fontsize=11)
                    ax.grid(True, linestyle='--', alpha=0.5, color='gray')
                    ax.spines['top'].set_visible(False)
                    ax.spines['right'].set_visible(False)
                    fig.tight_layout()
                    buf = _io.BytesIO()
                    fig.savefig(buf, format="png", dpi=150, bbox_inches='tight')
                    plt.close(fig)
                    buf.seek(0)
                    with col:
                        st.download_button(
                            label=btn_label,
                            data=buf.getvalue(),
                            file_name=f"{airfoil_label}_{name}.png",
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
                line=dict(color=COLORS['c2'], width=3),
                fill='toself', fillcolor='rgba(0, 255, 255, 0.15)',
            ))
            fig1.add_hline(y=0, line_dash="dash", line_color=COLORS['border_strong'], opacity=0.3)
            fig1.update_layout(
                title=sp['filename'], xaxis_title="x/c", yaxis_title="y/c",
                height=350, plot_bgcolor=COLORS['bg_card'],
                paper_bgcolor=COLORS['bg_card'], font=dict(color=COLORS['text_dim']),
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
                f"""<div style="background:{COLORS['bg']};border:1px solid {COLORS['border']};border-radius:8px;
                padding:14px 18px 6px;font-family:'JetBrains Mono',monospace;
                font-size:13px;color:{COLORS['text_dim']};line-height:1.6;">
                <span style="color:{COLORS['c2']};font-weight:600;">AeroLab Parser</span>
                <span style="color:{COLORS['c3']};"> &gt;</span>
                <span style="color:{COLORS['text']};"> {sp['filename']}</span><br>
                <span style="color:{COLORS['c5']};">{fix_header}</span><br>
                <span style="color:{COLORS['c3']};white-space:pre-wrap;">{fix_lines}</span>
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

            sweep_bl_data = fr.get("bl_data")
            if sweep_bl_data:
                sweep_bl_rows = []
                for surface in ("upper", "lower"):
                    for row in sweep_bl_data.get(surface, []):
                        sweep_bl_rows.append({"surface": surface, **row})
                if sweep_bl_rows:
                    sweep_bl_csv = pd.DataFrame(sweep_bl_rows).to_csv(index=False)
                    st.download_button(
                        label="💾 Download BL Data (CSV, first converged α)",
                        data=sweep_bl_csv,
                        file_name=f"{sp['filename'].replace('.dat', '')}_bl_data.csv",
                        mime="text/csv",
                        key="sweep_bl_dl",
                        help="Boundary-layer data from the first converged angle of attack in the sweep"
                    )
            else:
                st.caption("ℹ️ BL data not available for this sweep (inviscid mode or convergence fallback)")

            st.markdown("---")
            st.subheader("🌊 Interactive Wind Tunnel")
            st.caption(
                "Live Lattice-Boltzmann (D2Q9) simulation of your airfoil. "
                "Adjust AOA, flow speed, and trail density with the sliders. "
                "Use 📷 Save PNG to capture the current view. "
                "Note: flow speed and Reynolds number shown here use the standard physical definitions "
                "(Re = Vc/ν) based on the flow-speed slider — independent of the XFOIL analysis above."
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

        lp_requested_mode = last_params.get('mode', 'viscous')
        lp_actual_mode = result.get("coefficients", {}).get("mode", lp_requested_mode)
        lp_fell_back = lp_requested_mode == "viscous" and lp_actual_mode == "inviscid"

        if lp_actual_mode == "viscous" and 'ncrit' in last_params:
            lp_mode_str = f"Viscous (NCrit={last_params['ncrit']})"
        else:
            lp_mode_str = lp_actual_mode.capitalize()
        if lp_fell_back:
            lp_mode_str += " ⚠️ fell back from Viscous"

        st.info(
            f"📊 **{last_params['filename']}** | Re = {last_params['reynolds']:,} | "
            f"α = {last_params['alpha']}° | {lp_mode_str}"
        )
        if lp_fell_back:
            st.warning(
                "⚠️ **Viscous solve did not converge for this case** — XFOIL fell back to inviscid "
                "(CD = 0, no BL data). Try a different Reynolds number, angle of attack, or NCrit."
            )

        if "coefficients" in result and result["coefficients"]:
            st.markdown("---")
            st.subheader("📊 Aerodynamic Coefficients")
            coeffs = result["coefficients"]

            if "CL" in coeffs and "CD" in coeffs:
                is_inviscid = coeffs.get("mode") == "inviscid" or coeffs["CD"] == 0
                ld = coeffs["CL"] / coeffs["CD"] if coeffs["CD"] != 0 else None
                if coeffs["CL"] < -0.1:
                    st.warning("⚠️ **Negative Lift Detected!** The airfoil is generating downforce.")
                elif abs(coeffs["CL"]) < 0.001:
                    st.info("ℹ️ **Near-Zero Lift:** Symmetric airfoil at zero AoA — L/D not meaningful.")
                elif is_inviscid:
                    st.info("ℹ️ **Inviscid Mode:** CD = 0 by design (no boundary-layer drag computed) — "
                            "L/D is undefined, and stall can't be detected without viscous data.")
                elif abs(last_params['alpha']) >= 12 and (coeffs["CD"] > 0.15 or ld < 5):
                    st.error("🚨 **Possible Stall Condition!** High drag and low L/D suggests flow separation.")

            coef_cols = st.columns(4)
            for idx, (label, key) in enumerate([("CL", "CL"), ("CD", "CD"), ("L/D", None), ("Cm", "Cm")]):
                with coef_cols[idx]:
                    if key and key in coeffs:
                        st.metric(label, f"{coeffs[key]:.4f}")
                    elif label == "L/D" and "CL" in coeffs and "CD" in coeffs:
                        if coeffs["CD"] == 0:
                            st.metric(label, "∞", help="Inviscid mode: CD = 0 (no viscous drag computed), so L/D is undefined")
                        elif abs(coeffs["CL"]) < 0.001:
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
                line=dict(color=COLORS['c2'], width=3),
                fill='toself', fillcolor='rgba(0, 255, 255, 0.15)',
                hovertemplate='x: %{x:.4f}<br>y: %{y:.4f}<extra></extra>'
            ))
            fig1.add_hline(y=0, line_dash="dash", line_color=COLORS['border_strong'], opacity=0.3)
            fig1.add_vline(x=0, line_dash="dash", line_color=COLORS['border_strong'], opacity=0.3)
            fig1.update_layout(
                title=last_params['filename'],
                xaxis_title="x/c", yaxis_title="y/c",
                height=400, hovermode='closest',
                plot_bgcolor=COLORS['bg_card'],
                paper_bgcolor=COLORS['bg_card'], font=dict(color=COLORS['text_dim']),
                yaxis=dict(scaleanchor="x", scaleratio=1)
            )
            fig1.update_xaxes(showgrid=True, gridcolor=COLORS['border'])
            fig1.update_yaxes(showgrid=True, gridcolor=COLORS['border'])
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
                background:{COLORS['bg']};
                border:1px solid {COLORS['border']};
                border-radius:8px;
                padding:14px 18px 6px;
                margin-bottom:8px;
                font-family:'JetBrains Mono',monospace;
                font-size:13px;
                color:{COLORS['text_dim']};
                line-height:1.6;
            ">
                <span style="color:{COLORS['c2']};font-weight:600;">AeroLab Parser</span>
                <span style="color:{COLORS['c3']};"> &gt;</span>
                <span style="color:{COLORS['text']};"> {last_params['filename']}</span><br>
                <span style="color:{COLORS['c5']};">{fix_header}</span><br>
                <span style="color:{COLORS['c3']};white-space:pre-wrap;">{fix_lines}</span>
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
                    line=dict(color=COLORS['c2'], width=3),
                    hovertemplate='x/c: %{x:.4f}<br>Cp: %{y:.4f}<extra></extra>'
                ))
                fig2.add_trace(go.Scatter(
                    x=cp_x[mid_idx:], y=cp_values[mid_idx:],
                    mode='lines', name='Lower surface',
                    line=dict(color=COLORS['c6'], width=3),
                    hovertemplate='x/c: %{x:.4f}<br>Cp: %{y:.4f}<extra></extra>'
                ))
                fig2.add_hline(y=0, line_dash="dash", line_color=COLORS['border_strong'], opacity=0.3)
                fig2.update_layout(
                    title=f"Re = {last_params['reynolds']:,.0f}, α = {last_params['alpha']}°",
                    xaxis_title="x/c", yaxis_title="Cp",
                    height=400, hovermode='closest',
                    plot_bgcolor=COLORS['bg_card'],
                    paper_bgcolor=COLORS['bg_card'], font=dict(color=COLORS['text_dim']),
                    yaxis=dict(autorange='reversed')
                )
                fig2.update_xaxes(showgrid=True, gridcolor=COLORS['border'])
                fig2.update_yaxes(showgrid=True, gridcolor=COLORS['border'])
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
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            if st.button("💾 Download Results as CSV"):
                csv_data = pd.DataFrame({'x': result["cp_x"], 'Cp': result["cp_values"]})
                csv = csv_data.to_csv(index=False)
                st.download_button(
                    label="Download Cp Data",
                    data=csv,
                    file_name=f"{last_params['filename'].replace('.dat', '')}_cp_results.csv",
                    mime="text/csv",
                    key="single_cp_dl"
                )
        with dl_col2:
            bl_data = result.get("bl_data")
            if bl_data:
                bl_rows = []
                for surface in ("upper", "lower"):
                    for row in bl_data.get(surface, []):
                        bl_rows.append({"surface": surface, **row})
                if bl_rows:
                    bl_csv = pd.DataFrame(bl_rows).to_csv(index=False)
                    st.download_button(
                        label="💾 Download BL Data (CSV)",
                        data=bl_csv,
                        file_name=f"{last_params['filename'].replace('.dat', '')}_bl_data.csv",
                        mime="text/csv",
                        key="single_bl_dl",
                        help="Boundary-layer data: s, x, y, Dstar, Theta, Cf, H for upper and lower surfaces"
                    )
            else:
                st.caption("ℹ️ BL data not available (inviscid mode or convergence fallback)")

        # ── Airflow Visualization (LBM Wind Tunnel) ─────────────────────────
        st.markdown("---")
        st.subheader("🌊 Interactive Wind Tunnel")
        st.caption(
            "Live Lattice-Boltzmann (D2Q9) simulation of your airfoil. "
            "Adjust AOA, flow speed, and trail density with the sliders. "
            "Use 📷 Save PNG to capture the current view. "
            "Note: flow speed and Reynolds number shown here use the standard physical definitions "
            "(Re = Vc/ν) based on the flow-speed slider — independent of the XFOIL analysis above."
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