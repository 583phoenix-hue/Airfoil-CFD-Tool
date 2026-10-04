import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";
import StatusBanner from "../components/StatusBanner.jsx";
import AirfoilPicker from "../components/AirfoilPicker.jsx";
import { Alert, Checkbox, Details, NumberField, Segmented, Spinner } from "../components/ui.jsx";
import Plot, { chartLayout, decorations, hline, vline, vlines } from "../lib/Plot.jsx";
import { postForm } from "../lib/http.js";
import { downloadText, toCsv } from "../lib/files.js";
import { useBackendStatus } from "../useBackendStatus.js";
import { COLORS } from "../config.js";
import { MODULES } from "./Aeroelasticity.jsx";

const DEFAULTS = {
  divergence: { alpha_root: 2, k_alpha: 2000, x_ea: 35, chord: 1, span: 1, rho: 1.225, v_start: 5, v_step: 5, v_max: 100 },
  reversal: { alpha_root: 2, k_alpha: 2000, x_ea: 35, flap_frac: 0.25, chord: 1, span: 1, rho: 1.225, flap_source: "xfoil", v_start: 2, v_step: 5, v_max: 100 },
  flutter: { m: 38.49, mu: 8.082, xcg: 55, xea: 45, kh: 9.621, ktheta: 9.621, chord: 2, rho: 1.225, alpha_ref: 2, use_real: true, v_start: 0.1, v_step: 0.5, v_max: 100 },
};

// Results are kept per module for the session, so going back and forth doesn't lose them.
const lastResults = {};

function ResultCard({ label, value, color, children }) {
  return (
    <div className="card result-card">
      <div style={{ fontSize: 13, marginBottom: 4 }}>{label}</div>
      <div style={{ fontFamily: "var(--font-head)", fontSize: 32, fontWeight: 600, color }}>{value}</div>
      {children && <div className="result-sub">{children}</div>}
    </div>
  );
}

const lineTrace = (x, y, name, color, markers = true) => ({
  x, y, name, mode: markers ? "lines+markers" : "lines", line: { color, width: 3 }, marker: { size: 5 },
});

function aeroLayout(xTitle, yTitle, deco, extra = {}) {
  return chartLayout({ xTitle, yTitle, height: 330, hovermode: "x unified", ...deco, ...extra });
}

function PolarDetails({ polar }) {
  const cl = useMemo(() => polar && [lineTrace(polar.alpha, polar.cl, "Cl", COLORS.c2)], [polar]);
  const cm = useMemo(() => polar && [lineTrace(polar.alpha, polar.cm, "Cm", COLORS.c4)], [polar]);
  const lay = useMemo(() => ({
    cl: chartLayout({ xTitle: "α (deg)", yTitle: "Cl", height: 280, legend: false }),
    cm: chartLayout({ xTitle: "α (deg)", yTitle: "Cm c/4", height: 280, legend: false }),
  }), []);
  if (!polar) return null;
  return (
    <Details summary="Airfoil data used (converged XFOIL polar)">
      <div className="grid grid-2">
        <Plot title="Lift coefficient" data={cl} layout={lay.cl} filename="polar_cl" />
        <Plot title="Quarter-chord moment coefficient" data={cm} layout={lay.cm} filename="polar_cm" />
      </div>
      <button className="btn btn-secondary btn-sm" style={{ marginTop: 8 }}
        onClick={() => downloadText("aerolab_polar.csv", toCsv(polar.alpha.map((a, i) => ({
          alpha_deg: a, cl: polar.cl[i], cd: polar.cd?.[i], cm_c4: polar.cm[i] }))), "text/csv")}>⬇️ Polar (CSV)</button>
    </Details>
  );
}

const n = (v, d) => (v === null || v === undefined ? 0 : v).toFixed(d);

function DivergenceResult({ r, p }) {
  const lin = r.linear || {};
  const reason = r.stopped_reason;
  const linTxt = lin.v_div ? `Linear theory: ${lin.v_div.toFixed(1)} m/s`
    : "Linear theory: no divergence (elastic axis not aft of the aerodynamic centre)";
  const sub = `${linTxt} · aerodynamic centre at ${n((lin.x_ac_over_c || 0) * 100, 1)}% chord · a₀ = ${n(lin.a0_per_rad, 2)} /rad`;
  let card;
  if (reason === "divergence_found") {
    card = <ResultCard label="Divergence speed" value={`${r.v_div.toFixed(1)} m/s`} color={COLORS.c6}>
      Elastic twist at divergence: {r.alpha_elastic_at_div_deg.toFixed(2)}° (total α {r.alpha_total_at_div_deg.toFixed(2)}°)<br />{sub}</ResultCard>;
  } else if (reason === "stall_limited_divergence") {
    card = <ResultCard label="Divergence speed (twist runaway)" value={`≈ ${r.v_div.toFixed(1)} m/s`} color={COLORS.c6}>{sub}</ResultCard>;
  } else if (reason === "no_divergence_possible") {
    card = <ResultCard label="Divergence speed" value="None" color={COLORS.c3}>The twist settles to a finite value at any speed.<br />{sub}</ResultCard>;
  } else if (reason === "polar_range_exceeded") {
    card = <ResultCard label="Divergence speed" value="Not reached" color={COLORS.c4}>The section left XFOIL's converged range before diverging (see below).<br />{sub}</ResultCard>;
  } else {
    card = <ResultCard label="Divergence speed" value={`> ${p.v_max.toFixed(0)} m/s`} color={COLORS.c3}>No divergence within the swept range.<br />{sub}</ResultCard>;
  }
  const hist = r.history || [];
  const v = hist.map((h) => h.v);
  const twist = useMemo(() => [lineTrace(v, hist.map((h) => h.alpha_elastic_deg), "Elastic twist", COLORS.c2)], [r]);
  const twistLay = useMemo(() => aeroLayout("Airspeed (m/s)", "Twist (deg)",
    vlines([[r.v_div, "divergence", COLORS.c6], [lin.v_div, "linear theory", COLORS.textDim, "dash"]]),
    { legend: false }), [r]);
  const keff = useMemo(() => [lineTrace(v, hist.map((h) => (h.k_eff != null ? h.k_eff / p.k_alpha : null)), "K_eff / k_α", COLORS.c5)], [r]);
  const keffLay = useMemo(() => aeroLayout("Airspeed (m/s)", "K_eff / k_α",
    decorations(hline(0), vline(r.v_div, "divergence", COLORS.c6)), { legend: false, yRange: [-0.1, 1.25] }), [r]);
  return (
    <>
      {card}
      {(r.warnings || []).map((w, i) => <Alert key={i} kind="warn">{w}</Alert>)}
      {hist.length > 0 && (
        <div className="grid grid-2">
          <Plot title="Elastic twist vs airspeed" data={twist} layout={twistLay} filename="divergence_twist" />
          <Plot title="Effective torsional stiffness (1 = rigid, 0 = diverges)" data={keff} layout={keffLay} filename="divergence_keff" />
        </div>
      )}
      <HistoryCsv rows={hist} name="divergence_history.csv" />
      <PolarDetails polar={r.polar} />
    </>
  );
}

function ReversalResult({ r, p }) {
  const lin = r.linear || {};
  const fd = r.flap_derivatives || {};
  const src = fd.source === "xfoil" ? "XFOIL" : "thin-airfoil theory";
  const linTxt = lin.v_reversal ? `Linear theory: ${lin.v_reversal.toFixed(1)} m/s` : "Linear theory: no reversal";
  const sub = (
    <>
      {linTxt} · flap derivatives from {src}: Cl<sub>δ</sub> = {n(fd.cl_delta_per_rad, 2)}, Cm<sub>δ</sub> ={" "}
      {n(fd.cm_c4_delta_per_rad, 3)} /rad (thin-airfoil: {n(fd.thin_airfoil_cl_delta_per_rad, 2)},{" "}
      {n(fd.thin_airfoil_cm_c4_delta_per_rad, 3)})<br />Real lift-curve slope: {n(r.a0_per_rad, 2)} /rad
    </>
  );
  const reason = r.stopped_reason;
  let card;
  if (r.v_reversal != null) card = <ResultCard label="Control reversal speed" value={`${r.v_reversal.toFixed(1)} m/s`} color={COLORS.c5}>{sub}</ResultCard>;
  else if (reason === "divergence_before_reversal") {
    card = <ResultCard label="Control reversal speed" value="Pre-empted by divergence" color={COLORS.c6}>
      Divergence at {r.v_div.toFixed(1)} m/s comes first.<br />{sub}</ResultCard>;
  } else {
    card = <ResultCard label="Control reversal speed" value={reason === "no_reversal_within_range" ? `> ${p.v_max.toFixed(0)} m/s` : "Not reached"}
      color={COLORS.c3}>{sub}</ResultCard>;
  }
  const hist = r.history || [];
  const v = hist.map((h) => h.v);
  const eff = useMemo(() => [lineTrace(v, hist.map((h) => h.effectiveness), "Effectiveness", COLORS.c5)], [r]);
  const effLay = useMemo(() => aeroLayout("Airspeed (m/s)", "Aeroelastic / rigid dCl/dδ",
    decorations(hline(0), hline(1, COLORS.border, "dot"), vlines([[r.v_reversal, "reversal", COLORS.c5],
      [lin.v_reversal, "linear theory", COLORS.textDim, "dash"], [r.v_div, "divergence", COLORS.c6, "dot"]])),
    { legend: false }), [r]);
  const twist = useMemo(() => [lineTrace(v, hist.map((h) => h.alpha_elastic_deg), "Elastic twist", COLORS.c2)], [r]);
  const twistLay = useMemo(() => aeroLayout("Airspeed (m/s)", "Twist (deg)",
    decorations(vline(r.v_reversal, "reversal", COLORS.c5)), { legend: false }), [r]);
  return (
    <>
      {card}
      {(r.warnings || []).map((w, i) => <Alert key={i} kind="warn">{w}</Alert>)}
      {hist.length > 0 && (
        <div className="grid grid-2">
          <Plot title="Flap effectiveness (1 = rigid wing, <0 = reversed)" data={eff} layout={effLay} filename="reversal_effectiveness" />
          <Plot title="Elastic twist at zero flap deflection" data={twist} layout={twistLay} filename="reversal_twist" />
        </div>
      )}
      <HistoryCsv rows={hist} name="reversal_history.csv" />
      <PolarDetails polar={r.polar} />
    </>
  );
}

function FlutterResult({ r, p }) {
  const reason = r.stopped_reason;
  const unc = r.uncoupled || {};
  const ai = r.aero_info;
  const a0Txt = ai ? `XFOIL lift-curve slope ${ai.a0_per_rad.toFixed(2)} /rad (×${n(r.a0_scale ?? 1, 3)} of 2π)`
    : "thin-airfoil lift-curve slope (2π)";
  const subBase = `Uncoupled frequencies: plunge ${n(unc.omega_h, 2)} rad/s, pitch ${n(unc.omega_theta, 2)} rad/s · ${a0Txt}`;
  let card;
  if (reason === "flutter_found" && r.omega_flutter) {
    const fhz = r.omega_flutter / (2 * Math.PI);
    const mode = { pitch: "pitch-dominated", plunge: "plunge-dominated" }[r.critical_mode] || "";
    card = <ResultCard label="Flutter speed" value={`${r.U_flutter.toFixed(2)} m/s`} color={COLORS.c2}>
      Flutter frequency: {r.omega_flutter.toFixed(2)} rad/s ({fhz.toFixed(2)} Hz) · reduced frequency k = {r.k_flutter.toFixed(3)} · {mode} mode<br />{subBase}</ResultCard>;
  } else if (reason === "flutter_found") {
    card = <ResultCard label="Flutter speed" value={`${r.U_flutter.toFixed(2)} m/s`} color={COLORS.c2}>{subBase}</ResultCard>;
  } else if (reason === "unstable_at_start") {
    card = <ResultCard label="Flutter speed" value={`< ${p.v_start} m/s`} color={COLORS.c6}>{subBase}</ResultCard>;
  } else {
    card = <ResultCard label="Flutter speed" value={`> ${p.v_max} m/s`} color={COLORS.c3}>No flutter within the swept range.<br />{subBase}</ResultCard>;
  }
  const modes = r.modes || [];
  const U = modes.map((m) => m.U);
  const series = [["plunge", "Plunge-origin mode", COLORS.c3], ["pitch", "Pitch-origin mode", COLORS.c5]];
  const vg = useMemo(() => series.map(([k, name, col]) => lineTrace(U, modes.map((m) => (m[k] || {}).damping ?? null), name, col, false)), [r]);
  const vgLay = useMemo(() => aeroLayout("Airspeed (m/s)", "Damping, Re(s) (1/s)",
    decorations(hline(0), vline(r.U_flutter, "flutter", COLORS.c2))), [r]);
  const vf = useMemo(() => series.map(([k, name, col]) => lineTrace(U, modes.map((m) => (m[k] || {}).freq_hz ?? null), name, col, false)), [r]);
  const vfLay = useMemo(() => aeroLayout("Airspeed (m/s)", "Frequency (Hz)", decorations(vline(r.U_flutter, "flutter", COLORS.c2))), [r]);
  const csvRows = modes.map((m) => ({
    U: m.U, plunge_damping: m.plunge?.damping, plunge_freq_hz: m.plunge?.freq_hz,
    pitch_damping: m.pitch?.damping, pitch_freq_hz: m.pitch?.freq_hz,
  }));
  return (
    <>
      {card}
      {(r.warnings || []).map((w, i) => <Alert key={i} kind="warn">{w}</Alert>)}
      {modes.length > 0 && (
        <div className="grid grid-2">
          <Plot title="V-g diagram (damping crosses 0 at flutter)" data={vg} layout={vgLay} filename="flutter_vg" />
          <Plot title="V-f diagram (frequencies approach at flutter)" data={vf} layout={vfLay} filename="flutter_vf" />
        </div>
      )}
      <HistoryCsv rows={csvRows} name="flutter_vg_vf.csv" />
    </>
  );
}

function HistoryCsv({ rows, name }) {
  if (!rows?.length) return null;
  return (
    <div>
      <button className="btn btn-secondary btn-sm" onClick={() => downloadText(name, toCsv(rows), "text/csv")}>⬇️ Sweep data (CSV)</button>
    </div>
  );
}

function AeroRun({ module }) {
  const status = useBackendStatus();
  const valid = Object.prototype.hasOwnProperty.call(MODULES, module);
  const [airfoil, setAirfoil] = useState(null);
  const [reynolds, setReynolds] = useState(500_000);
  const [ncrit, setNcrit] = useState(9);
  const [p, setP] = useState(() => ({ ...(DEFAULTS[module] || {}) }));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(() => lastResults[module] || null);

  useEffect(() => {
    if (valid) document.title = `${MODULES[module].name} - AeroLab`;
  }, [module, valid]);

  if (!valid) return <Navigate to="/aeroelasticity" replace />;
  const set = (k) => (v) => setP((o) => ({ ...o, [k]: v }));

  const run = async () => {
    if (p.v_max <= p.v_start) { setError("'Sweep up to' must be larger than 'Sweep from'."); return; }
    setRunning(true);
    setError(null);
    let path;
    let fields;
    if (module === "divergence") {
      path = "/aeroelasticity/divergence";
      fields = { reynolds, ncrit, alpha_root: p.alpha_root, k_alpha: p.k_alpha, x_ea_over_c: p.x_ea / 100, chord: p.chord,
        span: p.span, rho: p.rho, v_start: p.v_start, v_step: p.v_step, v_max: p.v_max };
    } else if (module === "reversal") {
      path = "/aeroelasticity/reversal";
      fields = { reynolds, ncrit, alpha_root: p.alpha_root, k_alpha: p.k_alpha, x_ea_over_c: p.x_ea / 100, chord: p.chord,
        span: p.span, rho: p.rho, flap_chord_fraction: p.flap_frac, flap_source: p.flap_source,
        v_start: p.v_start, v_step: p.v_step, v_max: p.v_max };
    } else {
      path = "/aeroelasticity/flutter";
      fields = { reynolds, ncrit, alpha_ref: p.alpha_ref, m: p.m, mu: p.mu, xCG_percent: p.xcg, xEA_percent: p.xea,
        kh: p.kh, ktheta: p.ktheta, chord: p.chord, rho: p.rho, use_real_airfoil_data: p.use_real ? "true" : "false",
        v_start: p.v_start, v_step: p.v_step, v_max: p.v_max };
    }
    try {
      const r = await postForm(path, fields, {
        file: airfoil ? { name: airfoil.name, content: airfoil.content } : null, timeoutMs: 280000, retries: 0 });
      const entry = { r, p: { ...p }, airfoil: airfoil?.name || "NACA 0012", reynolds };
      lastResults[module] = entry;
      setResult(entry);
    } catch (e) {
      setError(`Analysis failed: ${e.message}`);
    } finally {
      setRunning(false);
    }
  };

  const num = (label, k, opts = {}) => <NumberField label={label} value={p[k]} onChange={set(k)} {...opts} />;

  return (
    <>
      <Logo />
      <CmapBar />
      <Link to="/aeroelasticity" className="btn btn-secondary btn-sm">← Back to modules</Link>
      <div className="aero-form">
        <h1 style={{ fontSize: "clamp(24px,3.5vw,36px)", lineHeight: 1.1, margin: "20px 0 4px" }}>{MODULES[module].name}</h1>
        <p className="tool-sub">{MODULES[module].tagline}</p>
        <StatusBanner status={status} />

        <div className="card stack" style={{ marginTop: 16 }}>
          <AirfoilPicker value={airfoil} onChange={setAirfoil} label="Airfoil" defaultLabel="NACA 0012 (default)" />
          <div className="grid grid-2">
            <NumberField label="Reynolds number" value={reynolds} min={10_000} max={10_000_000} step={50_000} onChange={setReynolds} />
            <NumberField label="N-crit (transition sensitivity)" value={ncrit} min={0.1} max={20} step={0.5} onChange={setNcrit} />
          </div>

          <div className="subhead">Structural properties</div>
          {module !== "flutter" ? (
            <div className="grid grid-2">
              <div className="stack">
                {num("Root angle of attack (deg)", "alpha_root")}
                {num("Torsional stiffness k_α (N·m/rad)", "k_alpha", { min: 1 })}
                {num("Elastic axis location (% chord from LE)", "x_ea", { min: 0, max: 100 })}
                {module === "reversal" && num("Flap chord fraction", "flap_frac", { min: 0.05, max: 0.6, step: 0.05 })}
              </div>
              <div className="stack">
                {num("Chord (m)", "chord", { min: 0.01 })}
                {num("Span (m)", "span", { min: 0.01 })}
                {num("Air density (kg/m³)", "rho", { min: 0.01 })}
                {module === "reversal" && (
                  <div className="field">
                    <span className="field-label">Flap derivatives from</span>
                    <Segmented value={p.flap_source} onChange={set("flap_source")} ariaLabel="Flap derivatives from"
                      options={[["xfoil", "XFOIL (viscous)"], ["thin_airfoil", "Thin-airfoil theory"]]} />
                    <div className="caption">XFOIL deflects the flap ±2° and measures the change in lift and moment, including
                      viscous losses. Thin-airfoil theory is the classic analytic result, scaled by the airfoil's real lift-curve slope.</div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-2">
                <div className="stack">
                  {num("Mass per unit span (kg/m)", "m", { min: 0.01 })}
                  {num("Mass moment of inertia about CG (kg·m)", "mu", { min: 0.001 })}
                  {num("Center of gravity (% chord from LE)", "xcg", { min: 0, max: 100 })}
                  {num("Elastic axis (% chord from LE)", "xea", { min: 0, max: 100 })}
                </div>
                <div className="stack">
                  {num("Plunge stiffness k_h (N/m)", "kh", { min: 0.1 })}
                  {num("Torsional stiffness k_θ (N·m/rad)", "ktheta", { min: 0.1 })}
                  {num("Chord (m)", "chord", { min: 0.01 })}
                  {num("Air density (kg/m³)", "rho", { min: 0.01 })}
                </div>
              </div>
              {num("Reference angle of attack for real airfoil data (deg)", "alpha_ref")}
              <Checkbox label="Use real, XFOIL-measured lift-curve slope (vs. thin-airfoil theory)" checked={p.use_real} onChange={set("use_real")} />
            </>
          )}

          <div className="subhead">Airspeed sweep</div>
          <div className="grid grid-3">
            {num("Sweep from (m/s)", "v_start", { min: 0.01 })}
            {num("Sweep step (m/s)", "v_step", { min: 0.01 })}
            {num("Sweep up to (m/s)", "v_max", { min: 1 })}
          </div>

          <button className="btn btn-block" onClick={run} disabled={running || status === "unavailable"}>
            {running ? "Running…" : "Run analysis"}
          </button>
          {running && <Spinner>Running XFOIL and solving the aeroelastic equilibrium…</Spinner>}
          {error && <Alert kind="error">{error}</Alert>}
        </div>

        {result && (
          <div className="stack-lg" style={{ marginTop: 24 }}>
            <div className="caption">Result for <strong>{result.airfoil}</strong> · Re = {Number(result.reynolds).toLocaleString()}</div>
            {module === "divergence" && <DivergenceResult r={result.r} p={result.p} />}
            {module === "reversal" && <ReversalResult r={result.r} p={result.p} />}
            {module === "flutter" && <FlutterResult r={result.r} p={result.p} />}
          </div>
        )}
      </div>
      <Footer />
    </>
  );
}

// Remount per module so form state and results never leak between modules.
export default function AeroRunPage() {
  const { module } = useParams();
  return <AeroRun key={module} module={module} />;
}
