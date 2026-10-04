import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";
import StatusBanner from "../components/StatusBanner.jsx";
import AirfoilPicker from "../components/AirfoilPicker.jsx";
import LbmFrame from "../components/LbmFrame.jsx";
import {
  Alert, Checkbox, Details, FileDrop, Metric, NumberField, ParserBox, Progress, RangeField,
  SectionTitle, Segmented, SelectField, SliderField, Spinner,
} from "../components/ui.jsx";
import Plot, { chartLayout, downloadMplPng, hline } from "../lib/Plot.jsx";
import { postForm, ApiError } from "../lib/http.js";
import { downloadText, readFileText, stem, toCsv } from "../lib/files.js";
import { useBackendStatus } from "../useBackendStatus.js";
import { COLORS } from "../config.js";

const RE_PRESETS = [
  ["custom", "Custom", null],
  ["50k", "Model Aircraft (50k)", 50_000],
  ["100k", "Small UAV (100k)", 100_000],
  ["500k", "Light Aircraft (500k)", 500_000],
  ["1M", "Glider (1M)", 1_000_000],
  ["3M", "Small Plane (3M)", 3_000_000],
  ["6M", "Airliner (6M)", 6_000_000],
];
const STEP_OPTIONS = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5];
const MAX_BATCH = 10;

// Same request is never sent twice in a session (Streamlit cached these for an hour).
const resultCache = new Map();
function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36);
}

async function runXfoil(file, p, signal) {
  const key = [hash(file.content), file.name, p.reynolds, p.alpha, p.ncrit, p.mode, p.mach].join("|");
  if (resultCache.has(key)) return resultCache.get(key);
  const res = await postForm("/upload_airfoil/", {
    reynolds: p.reynolds, alpha: p.alpha, ncrit: p.ncrit, mode: p.mode, mach: p.mach,
  }, { file: { name: /\.(dat|txt)$/i.test(file.name) ? file.name : `${file.name}.dat`, content: file.content },
    timeoutMs: 90000, retries: 1, signal });
  resultCache.set(key, res);
  if (resultCache.size > 200) resultCache.delete(resultCache.keys().next().value);
  return res;
}

const fmt = (v, d) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toFixed(d));
const displayName = (n) => stem(n).replace(/_/g, " ");
const modeLabel = (mode, ncrit) => (mode === "viscous" ? `Viscous (NCrit=${ncrit})` : "Inviscid");
const fellBack = (requested, res) => requested === "viscous" && res?.coefficients?.mode === "inviscid";

function rowFromResult(res, requested) {
  const c = res.coefficients || {};
  const ld = c.CL != null && c.CD ? c.CL / c.CD : null;
  return {
    CL: c.CL ?? null, CD: c.CD ?? null, "L/D": ld, Cm: c.Cm ?? null,
    Status: fellBack(requested, res) ? "⚠️ Fallback (Inviscid)" : "✅ Converged",
  };
}

// ── Charts ───────────────────────────────────────────────────────────────
function GeometryChart({ coords, title, height = 400 }) {
  const data = useMemo(() => [{
    x: coords.map((p) => p[0]), y: coords.map((p) => p[1]), mode: "lines", name: "Airfoil",
    line: { color: COLORS.c2, width: 3 }, fill: "toself", fillcolor: "rgba(0,255,255,0.15)",
    hovertemplate: "x: %{x:.4f}<br>y: %{y:.4f}<extra></extra>",
  }], [coords]);
  const layout = useMemo(() => chartLayout({ xTitle: "x/c", yTitle: "y/c", height, equal: true, legend: false,
    shapes: [hline(0)] }), [height]);
  return <Plot title={title} data={data} layout={layout} filename={`${stem(title)}_geometry`} />;
}

function CpChart({ cpX, cpV, title, height = 400 }) {
  const data = useMemo(() => {
    const mid = Math.floor(cpX.length / 2);
    return [
      { x: cpX.slice(0, mid), y: cpV.slice(0, mid), mode: "lines", name: "Upper surface",
        line: { color: COLORS.c2, width: 3 }, hovertemplate: "x/c: %{x:.4f}<br>Cp: %{y:.4f}<extra></extra>" },
      { x: cpX.slice(mid), y: cpV.slice(mid), mode: "lines", name: "Lower surface",
        line: { color: COLORS.c6, width: 3 }, hovertemplate: "x/c: %{x:.4f}<br>Cp: %{y:.4f}<extra></extra>" },
    ];
  }, [cpX, cpV]);
  const layout = useMemo(() => chartLayout({ xTitle: "x/c", yTitle: "Cp", height, reverseY: true,
    shapes: [hline(0)] }), [height]);
  return <Plot title={title} data={data} layout={layout} filename="aerolab_cp" />;
}

function ResultTable({ rows, columns, digits = {} }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className={typeof r[c] === "number" ? "mono num" : ""}>
                  {typeof r[c] === "number" ? (digits[c] !== undefined ? fmt(r[c], digits[c]) : r[c]) : (r[c] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Shared result pieces ─────────────────────────────────────────────────
function ParserSection({ filename, res }) {
  const coordText = "AIRFOIL\n" + res.coords_after.map(([x, y]) => `  ${x.toFixed(6)}  ${y.toFixed(6)}`).join("\n");
  return (
    <>
      <SectionTitle>🔧 Parser output</SectionTitle>
      <ParserBox filename={filename} fixes={res.parser_fixes} />
      <Details summary="📄 View parsed coordinates">
        <pre className="code-block">{coordText}</pre>
        <button className="btn btn-secondary btn-sm"
          onClick={() => downloadText(`${stem(filename)}_parsed.dat`, coordText)}>⬇️ Download parsed .dat</button>
      </Details>
    </>
  );
}

function blCsv(bl) {
  const rows = [];
  for (const surface of ["upper", "lower"]) for (const r of bl[surface] || []) rows.push({ surface, ...r });
  return rows.length ? toCsv(rows) : null;
}

export function TunnelNote() {
  return (
    <p className="caption" style={{ marginBottom: 12 }}>
      Live 2D lattice-Boltzmann simulation of your airfoil at a <strong>low Reynolds number (about 1,300–4,300)</strong>,
      set with the Reynolds slider. That's the scale of an insect or a tiny drone wing, so the flow separates earlier
      and the CL/CD shown here will not match the XFOIL results above, which are at your chosen Re. Speeds are shown
      as multiples of the freestream (× U∞). Use the Field menu for velocity, pressure, vorticity or smoke.
    </p>
  );
}

function WindTunnel({ coords, name }) {
  return (
    <>
      <SectionTitle>🌊 Interactive wind tunnel</SectionTitle>
      <TunnelNote />
      <LbmFrame coords={coords} name={name} />
      <Details summary="ℹ️ About this visualisation">
        <p><strong>Interactive wind tunnel: D2Q9 lattice-Boltzmann, 640×320 grid, Smagorinsky LES (WebGL2)</strong></p>
        <ul>
          <li><strong>Velocity</strong>: speed relative to the freestream; dark blue = slow, red = fast</li>
          <li><strong>Pressure (Cp)</strong>: blue = suction (low pressure), red = high pressure</li>
          <li><strong>Vorticity</strong>: red = counter-clockwise rotation, blue = clockwise; shows the shear layers and shed vortices</li>
          <li><strong>Smoke</strong>: thin streams of dye released upstream, carried by the flow</li>
          <li><strong>Show trails</strong>: tracer lines that follow the air and show its direction</li>
          <li><strong>Angle of attack</strong>: pitches the airfoil in real time; the freestream stays horizontal</li>
          <li><strong>Reynolds number</strong>: the simulation's own Re (U·c/ν); higher = less viscous, more vigorous shedding</li>
          <li><strong>Save PNG</strong>: downloads the current view</li>
        </ul>
        <p className="caption"><em>What it shows faithfully: the flow pattern of a 2D airfoil at this low Re (stagnation
          point, separation, vortex shedding). What it doesn't: a full-size wing. Real wings fly at Re in the millions,
          which would need thousands of times more grid cells than a browser can run. Being 2D, shed vortices are also
          more regular and stronger than on a real 3D wing, and the nearby tunnel walls raise CL. Treat the CL/CD values
          as rough indications.</em></p>
      </Details>
    </>
  );
}

// ── Single-point result ──────────────────────────────────────────────────
function SingleResult({ res, p }) {
  const c = res.coefficients || {};
  const fb = fellBack(p.mode, res);
  const actualMode = c.mode || p.mode;
  const isInviscid = actualMode === "inviscid" || c.CD === 0;
  const ld = c.CD ? c.CL / c.CD : null;
  const coords = res.coords_after;
  const xs = coords.map((q) => q[0]);
  const ys = coords.map((q) => q[1]);
  const blText = res.bl_data ? blCsv(res.bl_data) : null;

  let ldText = "N/A";
  if (c.CL != null && c.CD != null) {
    if (c.CD === 0) ldText = "∞";
    else if (Math.abs(c.CL) < 0.001) ldText = "~0";
    else ldText = ld.toFixed(2);
  }

  let liftNote = null;
  if (c.CL != null && c.CD != null) {
    if (c.CL < -0.1) liftNote = <Alert kind="warn">⚠️ <strong>Negative lift detected.</strong> The airfoil is generating downforce.</Alert>;
    else if (Math.abs(c.CL) < 0.001) liftNote = <Alert kind="info">ℹ️ <strong>Near-zero lift:</strong> symmetric airfoil at zero AoA, so L/D isn't meaningful.</Alert>;
    else if (isInviscid) liftNote = <Alert kind="info">ℹ️ <strong>Inviscid mode:</strong> CD = 0 by design (no boundary-layer drag computed), so L/D is undefined and stall can't be detected without viscous data.</Alert>;
    else if (Math.abs(p.alpha) >= 12 && (c.CD > 0.15 || ld < 5)) liftNote = <Alert kind="error">🚨 <strong>Possible stall.</strong> High drag and low L/D suggest flow separation.</Alert>;
  }

  return (
    <div className="stack-lg">
      <Alert kind="info">
        📊 <strong>{p.filename}</strong> · Re = {p.reynolds.toLocaleString()} · α = {p.alpha}° ·{" "}
        {actualMode === "viscous" ? `Viscous (NCrit=${p.ncrit})` : "Inviscid"}{fb ? " ⚠️ fell back from Viscous" : ""}
        {p.mach > 0 ? ` · M = ${p.mach}` : ""}
      </Alert>
      {fb && <Alert kind="warn">⚠️ <strong>The viscous solve did not converge for this case</strong>, so XFOIL fell back to
        inviscid (CD = 0, no BL data). Try a different Reynolds number, angle of attack, or NCrit.</Alert>}

      <div>
        <SectionTitle>📊 Aerodynamic coefficients</SectionTitle>
        {liftNote}
        <div className="grid grid-4" style={{ marginTop: liftNote ? 12 : 0 }}>
          <Metric label="CL" value={fmt(c.CL, 4)} />
          <Metric label="CD" value={fmt(c.CD, 4)} />
          <Metric label="L/D" value={ldText}
            help={c.CD === 0 ? "Inviscid mode: CD = 0 (no viscous drag computed), so L/D is undefined"
              : ld < 0 ? "Negative L/D = downforce" : undefined} />
          <Metric label="Cm" value={fmt(c.Cm, 4)} />
        </div>
      </div>

      <div className="grid grid-2">
        <div>
          <GeometryChart coords={coords} title={`🛩️ Geometry: ${p.filename}`} />
          <Details summary="🔍 Geometry details">
            <p><strong>Points:</strong> {coords.length}</p>
            <p><strong>Max thickness (y-range):</strong> {(Math.max(...ys) - Math.min(...ys)).toFixed(4)}</p>
            <p><strong>Chord length:</strong> {(Math.max(...xs) - Math.min(...xs)).toFixed(4)}</p>
          </Details>
        </div>
        <div>
          {res.cp_x?.length ? (
            <>
              <CpChart cpX={res.cp_x} cpV={res.cp_values}
                title={`📈 Pressure distribution: Re = ${p.reynolds.toLocaleString()}, α = ${p.alpha}°`} />
              <Details summary="📖 Understanding Cp">
                <ul>
                  <li>Negative Cp = lower pressure (suction)</li>
                  <li>Positive Cp = higher pressure</li>
                  <li>Upper surface: usually lower pressure (negative Cp)</li>
                  <li>Lower surface: usually higher pressure (positive Cp)</li>
                  <li>The difference between them creates lift.</li>
                </ul>
              </Details>
            </>
          ) : <Alert kind="warn">⚠️ No pressure coefficient data available.</Alert>}
        </div>
      </div>

      <ParserSection filename={p.filename} res={res} />

      <div className="btn-row">
        <button className="btn btn-secondary" disabled={!res.cp_x?.length}
          onClick={() => downloadText(`${stem(p.filename)}_cp_results.csv`,
            toCsv(res.cp_x.map((x, i) => ({ x, Cp: res.cp_values[i] }))), "text/csv")}>💾 Download Cp data (CSV)</button>
        {blText ? (
          <button className="btn btn-secondary" title="Boundary-layer data: s, x, y, Dstar, Theta, Cf, H for upper and lower surfaces"
            onClick={() => downloadText(`${stem(p.filename)}_bl_data.csv`, blText, "text/csv")}>💾 Download BL data (CSV)</button>
        ) : <span className="caption">ℹ️ BL data not available (inviscid mode or convergence fallback)</span>}
      </div>

      <WindTunnel coords={coords} name={displayName(p.filename)} />
    </div>
  );
}

// ── Sweep result ─────────────────────────────────────────────────────────
// [file suffix, on-page title, x key, y key, x label, y label, export title]
const POLARS = [
  ["CL_vs_AOA", "CL vs angle of attack", "α", "CL", "Angle of Attack α (°)", "Lift Coefficient CL", "CL vs Angle of Attack"],
  ["CD_vs_AOA", "CD vs angle of attack", "α", "CD", "Angle of Attack α (°)", "Drag Coefficient CD", "CD vs Angle of Attack"],
  ["CM_vs_AOA", "Cm vs angle of attack", "α", "Cm", "Angle of Attack α (°)", "Pitching Moment Cm", "Cm vs Angle of Attack"],
  ["CL_vs_CD", "Drag polar", "CD", "CL", "Drag Coefficient CD", "Lift Coefficient CL", "Drag Polar"],
  ["LD_vs_AOA", "L/D vs angle of attack", "α", "L/D", "Angle of Attack α (°)", "Lift-to-Drag Ratio L/D", "L/D vs Angle of Attack"],
];

function PolarChart({ rows, def, airfoil, reynolds }) {
  const [name, title, xk, yk, xl, yl, exportTitle] = def;
  const xs = useMemo(() => rows.map((r) => (xk === "α" ? r["α (°)"] : r[xk])), [rows, xk]);
  const ys = useMemo(() => rows.map((r) => r[yk]), [rows, yk]);
  const data = useMemo(() => [{
    x: xs, y: ys, mode: "lines+markers", line: { color: COLORS.c2, width: 2.5 }, marker: { size: 6 }, name: yk,
  }], [xs, ys, yk]);
  const layout = useMemo(() => chartLayout({ xTitle: xl, yTitle: yl, height: 300, legend: false }), [xl, yl]);
  return (
    <div>
      <Plot title={title} data={data} layout={layout} filename={`${airfoil}_${name}`} />
      <button className="btn btn-secondary btn-sm" style={{ marginTop: 6 }}
        onClick={() => downloadMplPng({ x: xs, y: ys, title: exportTitle,
          subtitle: `${airfoil} | Re = ${reynolds.toLocaleString("en-US")}`, xLabel: xl, yLabel: yl,
          filename: `${airfoil}_${name}` })}>⬇️ PNG</button>
    </div>
  );
}

function SweepResult({ rows, first, p }) {
  const nFallback = rows.filter((r) => r.Status.startsWith("⚠️")).length;
  const converged = rows.filter((r) => r.Status.startsWith("✅") && r.CL != null);
  const airfoil = stem(p.filename);
  const csvRows = rows.map((r) => ({ ...r, CL: r.CL ?? "—", CD: r.CD ?? "—", "L/D": r["L/D"] ?? "—", Cm: r.Cm ?? "—" }));
  const blText = first?.bl_data ? blCsv(first.bl_data) : null;
  return (
    <div className="stack-lg">
      <Alert kind="info">
        📊 <strong>{p.filename}</strong> · Re = {p.reynolds.toLocaleString()} · α = {p.alphaStart}° → {p.alphaEnd}° (step {p.alphaStep}°) · {modeLabel(p.mode, p.ncrit)}
      </Alert>
      {nFallback > 0 && <Alert kind="warn">⚠️ <strong>{nFallback} point(s) in this sweep didn't converge viscous</strong> and
        fell back to inviscid (CD = 0 for those points); see the Status column. They're left out of the polar plots since
        CD = 0 isn't physically meaningful.</Alert>}
      <div>
        <SectionTitle right={
          <button className="btn btn-secondary btn-sm"
            onClick={() => downloadText(`${airfoil}_sweep_Re${p.reynolds}.csv`,
              toCsv(csvRows, ["α (°)", "CL", "CD", "L/D", "Cm", "Status"]), "text/csv")}>⬇️ Export CSV</button>
        }>📋 AOA sweep results</SectionTitle>
        <ResultTable rows={rows} columns={["α (°)", "CL", "CD", "L/D", "Cm", "Status"]}
          digits={{ CL: 4, CD: 5, "L/D": 2, Cm: 4 }} />
      </div>

      {converged.length >= 2 && (
        <div>
          <SectionTitle>📈 Polar plots</SectionTitle>
          <div className="grid grid-2">
            {POLARS.map((def) => (
              <PolarChart key={def[0]} rows={converged} def={def} airfoil={airfoil} reynolds={p.reynolds} />
            ))}
          </div>
        </div>
      )}

      {first && (
        <>
          <div className="grid grid-2">
            <GeometryChart coords={first.coords_after} title={`🛩️ Geometry: ${p.filename}`} height={340} />
            <div>
              <ParserSection filename={p.filename} res={first} />
              <div style={{ marginTop: 12 }}>
                {blText ? (
                  <button className="btn btn-secondary btn-sm" title="Boundary-layer data from the first converged angle of attack in the sweep"
                    onClick={() => downloadText(`${airfoil}_bl_data.csv`, blText, "text/csv")}>💾 BL data (CSV, first converged α)</button>
                ) : <span className="caption">ℹ️ BL data not available for this sweep (inviscid mode or convergence fallback)</span>}
              </div>
            </div>
          </div>
          <WindTunnel coords={first.coords_after} name={displayName(p.filename)} />
        </>
      )}
    </div>
  );
}

// ── Batch result ─────────────────────────────────────────────────────────
function BatchResult({ rows, p }) {
  const nFallback = rows.filter((r) => r.Status.startsWith("⚠️")).length;
  const csvRows = rows.map((r) => ({ ...r, CL: r.CL ?? "—", CD: r.CD ?? "—", "L/D": r["L/D"] ?? "—", Cm: r.Cm ?? "—" }));
  return (
    <div className="stack-lg">
      <Alert kind="info">📦 <strong>Batch analysis</strong> · {rows.length} files · Re = {p.reynolds.toLocaleString()} · α = {p.alpha}° · {modeLabel(p.mode, p.ncrit)}</Alert>
      {nFallback > 0 && <Alert kind="warn">⚠️ <strong>{nFallback} file(s) didn't converge viscous</strong> and fell back to
        inviscid (CD = 0 for those rows); see the Status column.</Alert>}
      <div>
        <SectionTitle right={
          <button className="btn btn-secondary btn-sm"
            onClick={() => downloadText(`aerolab_batch_Re${p.reynolds}_alpha${p.alpha}.csv`,
              toCsv(csvRows, ["Airfoil", "CL", "CD", "L/D", "Cm", "Status"]), "text/csv")}>⬇️ Export CSV</button>
        }>📋 Batch results</SectionTitle>
        <ResultTable rows={rows} columns={["Airfoil", "CL", "CD", "L/D", "Cm", "Status"]}
          digits={{ CL: 4, CD: 5, "L/D": 2, Cm: 4 }} />
      </div>
    </div>
  );
}

// ── Compare result ───────────────────────────────────────────────────────
function CompareResult({ a, b, p }) {
  const items = [[p.filenameA, a], [p.filenameB, b]];
  const fbNames = items.filter(([, r]) => fellBack(p.mode, r)).map(([n]) => n);
  return (
    <div className="stack-lg">
      <Alert kind="info">⚖️ <strong>Comparing</strong> {p.filenameA} vs {p.filenameB} · Re = {p.reynolds.toLocaleString()} · α = {p.alpha}° · {modeLabel(p.mode, p.ncrit)}</Alert>
      {fbNames.length > 0 && <Alert kind="warn">⚠️ <strong>{fbNames.join(", ")}</strong> didn't converge viscous and fell back to
        inviscid (CD = 0 for that airfoil). Try a different Re, α, or NCrit.</Alert>}
      <SectionTitle>📋 Comparison</SectionTitle>
      <div className="grid grid-2">
        {items.map(([name, r]) => {
          const c = r.coefficients || {};
          const ld = c.CD ? c.CL / c.CD : null;
          return (
            <div key={name} className="stack">
              <div className="compare-name">{stem(name)}</div>
              <div className="grid grid-2" style={{ gap: 10 }}>
                <Metric label="CL" value={fmt(c.CL, 4)} />
                <Metric label="CD" value={fmt(c.CD, 5)} />
                <Metric label="L/D" value={c.CD === 0 ? "∞" : fmt(ld, 2)} help={c.CD === 0 ? "Inviscid: CD = 0, L/D undefined" : undefined} />
                <Metric label="Cm" value={fmt(c.Cm, 4)} />
              </div>
              <GeometryChart coords={r.coords_after} title={name} height={300} />
              {r.cp_x?.length ? <CpChart cpX={r.cp_x} cpV={r.cp_values} title="Pressure distribution" height={300} />
                : <p className="caption">ℹ️ No Cp data available</p>}
            </div>
          );
        })}
      </div>
      <SectionTitle>🌊 Interactive wind tunnel: side by side</SectionTitle>
      <TunnelNote />
      <LbmFrame coords={a.coords_after} name={p.filenameA} coordsB={b.coords_after} nameB={p.filenameB} />
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────
export default function Analysis() {
  const status = useBackendStatus();
  useEffect(() => { document.title = "Airfoil Analysis - AeroLab"; }, []);

  // parameters
  const [rePreset, setRePreset] = useState("500k");
  const [reynolds, setReynolds] = useState(500_000);
  const [mach, setMach] = useState(0);
  const [sweep, setSweep] = useState(false);
  const [alpha, setAlpha] = useState(5);
  const [range, setRange] = useState([-5, 15]);
  const [alphaStep, setAlphaStep] = useState(1);
  const [mode, setMode] = useState("viscous");
  const [ncrit, setNcrit] = useState(9);

  // inputs
  const [inputMode, setInputMode] = useState("single"); // single | batch | compare
  const [file, setFile] = useState(null);
  const [fileA, setFileA] = useState(null);
  const [fileB, setFileB] = useState(null);
  const [batchFiles, setBatchFiles] = useState([]);
  const [batchNote, setBatchNote] = useState(null);

  // run state
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const abortRef = useRef(null);

  const sweepActive = sweep && inputMode === "single";
  const alphas = useMemo(() => {
    const out = [];
    const n = Math.round((range[1] - range[0]) / alphaStep);
    for (let i = 0; i <= n; i++) {
      const a = Math.round((range[0] + i * alphaStep) * 100) / 100;
      if (a <= range[1] + 1e-9) out.push(a);
    }
    return out;
  }, [range, alphaStep]);

  const hasInput = inputMode === "single" ? !!file : inputMode === "compare" ? !!(fileA && fileB) : batchFiles.length > 0;
  const btnLabel = inputMode === "compare" ? "🚀 Run comparison" : inputMode === "batch" ? "🚀 Run batch analysis"
    : sweepActive ? `🚀 Run sweep (${alphas.length} runs)` : "🚀 Run analysis";

  const onBatchFiles = async (files) => {
    setBatchNote(null);
    let list = files.filter((f) => /\.(dat|txt)$/i.test(f.name) && f.size <= 1024 * 1024);
    if (list.length < files.length) setBatchNote("Some files were skipped (only .dat/.txt up to 1 MB).");
    if (list.length > MAX_BATCH) { setBatchNote(`⚠️ Maximum ${MAX_BATCH} files allowed. Only the first ${MAX_BATCH} will be analysed.`); list = list.slice(0, MAX_BATCH); }
    setBatchFiles(await Promise.all(list.map(async (f) => ({ name: f.name, content: await readFileText(f) }))));
  };

  const run = async () => {
    if (running || !hasInput) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setRunning(true);
    setError(null);
    setProgress(null);
    const base = { reynolds, ncrit, mode, mach };
    try {
      if (inputMode === "compare") {
        setProgress({ value: 0.3, text: `Analysing ${fileA.name} and ${fileB.name}…` });
        const p = { ...base, alpha };
        const [a, b] = await Promise.all([runXfoil(fileA, p, ctrl.signal), runXfoil(fileB, p, ctrl.signal)]);
        setResult({ kind: "compare", a, b, p: { ...p, filenameA: fileA.name, filenameB: fileB.name } });
      } else if (inputMode === "batch") {
        const rows = [];
        for (let i = 0; i < batchFiles.length; i++) {
          const f = batchFiles[i];
          setProgress({ value: i / batchFiles.length, text: `Analysing ${f.name}… (${i + 1}/${batchFiles.length} files)` });
          try {
            rows.push({ Airfoil: stem(f.name), ...rowFromResult(await runXfoil(f, { ...base, alpha }, ctrl.signal), mode) });
          } catch (e) {
            if (ctrl.signal.aborted) throw e;
            rows.push({ Airfoil: stem(f.name), CL: null, CD: null, "L/D": null, Cm: null, Status: "❌ Failed" });
          }
        }
        setResult({ kind: "batch", rows, p: { ...base, alpha } });
      } else if (sweepActive) {
        const rows = [];
        let first = null;
        for (let i = 0; i < alphas.length; i++) {
          const a = alphas[i];
          setProgress({ value: i / alphas.length, text: `Running α = ${a}°… (step ${i + 1} of ${alphas.length})` });
          try {
            const r = await runXfoil(file, { ...base, alpha: a }, ctrl.signal);
            if (!first) first = r;
            rows.push({ "α (°)": a, ...rowFromResult(r, mode) });
          } catch (e) {
            if (ctrl.signal.aborted) throw e;
            rows.push({ "α (°)": a, CL: null, CD: null, "L/D": null, Cm: null, Status: "❌ Failed" });
          }
        }
        setResult({ kind: "sweep", rows, first, p: { ...base, alphaStart: range[0], alphaEnd: range[1], alphaStep, filename: file.name } });
      } else {
        setProgress({ value: 0.4, text: "Computing… (30–60 s if the solver was asleep, otherwise a few seconds)" });
        const r = await runXfoil(file, { ...base, alpha }, ctrl.signal);
        setResult({ kind: "single", res: r, p: { ...base, alpha, filename: file.name } });
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e.message || e));
    } finally {
      setRunning(false);
      setProgress(null);
      abortRef.current = null;
    }
  };

  return (
    <>
      <Logo />
      <CmapBar />
      <div className="tool-layout">
        <aside className="tool-side">
          <div className="panel-title">⚙️ Parameters</div>
          <Link to="/choose" className="btn btn-secondary btn-block btn-sm">← Choose a tool</Link>

          <SelectField label="Reynolds number" value={rePreset}
            onChange={(v) => { setRePreset(v); const pr = RE_PRESETS.find((r) => r[0] === v); if (pr?.[2]) setReynolds(pr[2]); }}
            options={RE_PRESETS.map(([k, t]) => [k, t])} />
          <NumberField value={reynolds} min={10_000} max={10_000_000} step={10_000}
            onChange={(v) => { setReynolds(Math.round(v)); setRePreset("custom"); }}
            help="Higher Reynolds = less viscous effects. Allowed: 10,000 to 10,000,000." />

          <SliderField label="Mach number" value={mach} min={0} max={0.75} step={0.05} onChange={setMach}
            format={(v) => (v === 0 ? "0" : v.toFixed(2))}
            help="Freestream Mach number. Applies XFOIL's Karman-Tsien compressibility correction. 0 = incompressible, valid for most low-speed cases. The correction becomes unreliable above ~0.75 as shocks appear, which this panel method can't capture." />

          {mach === 0 && <div className="caption" style={{ marginTop: -8 }}>0 = incompressible</div>}
          <Checkbox label="AOA sweep" checked={sweepActive} disabled={inputMode !== "single"} onChange={setSweep}
            help="Sweep through a range of angles and build a polar table (single airfoil only)." />
          {sweepActive ? (
            <>
              <RangeField label="Sweep range" value={range} min={-10} max={20} step={0.5} onChange={setRange}
                format={(v) => `${v}°`} />
              <SelectField label="Step size" value={String(alphaStep)} onChange={(v) => setAlphaStep(parseFloat(v))}
                options={STEP_OPTIONS.map((s) => [String(s), `${s}°`])} />
              <div className="caption">Total runs: <strong>{alphas.length}</strong></div>
            </>
          ) : (
            <SliderField label="Angle of attack" value={alpha} min={-10} max={20} step={0.5} onChange={setAlpha}
              format={(v) => `${v}°`} help="Angle between the chord line and the freestream." />
          )}

          <div className="field">
            <span className="field-label">Analysis mode</span>
            <Segmented value={mode} onChange={setMode} ariaLabel="Analysis mode"
              options={[["viscous", "Viscous"], ["inviscid", "Inviscid"]]} />
            <div className="caption">{mode === "viscous" ? "Recommended: solves the boundary layer (real CD, BL data)."
              : "Fast, but CD is unrealistically low and no BL data is returned."}</div>
          </div>
          {mode === "viscous" ? (
            <SliderField label="NCrit (transition)" value={ncrit} min={0.1} max={14} step={0.1} onChange={setNcrit}
              format={(v) => v.toFixed(1)}
              help="Critical amplification factor for the e^N transition model. Lower (~4–6) = noisier environment (e.g. wind tunnel with grid). Higher (~9–11) = cleaner flow (e.g. sailplane in free air). Default 9." />
          ) : <div className="caption">NCrit isn't used in inviscid mode.</div>}

          <Details summary="ℹ️ About XFOIL">
            <p><strong>XFOIL</strong> is an industry-standard panel method code developed at MIT.</p>
            <p>Get airfoil files from the <a href="https://m-selig.ae.illinois.edu/ads/coord_database.html" target="_blank" rel="noreferrer">UIUC database</a> or{" "}
              <a href="http://airfoiltools.com/" target="_blank" rel="noreferrer">Airfoil Tools</a>.</p>
          </Details>
        </aside>

        <main className="tool-main">
          <h1 className="tool-h1">✈️ Airfoil Analysis</h1>
          <p className="tool-sub">Powered by the XFOIL panel method</p>
          <StatusBanner status={status} />

          <div className="card stack" style={{ marginTop: 16 }}>
            <Segmented value={inputMode} onChange={(v) => { setInputMode(v); setError(null); }} ariaLabel="Input mode"
              options={[["single", "Single airfoil"], ["batch", "📦 Batch (up to 10)"], ["compare", "⚖️ Compare two"]]} />

            {inputMode === "single" && <AirfoilPicker value={file} onChange={setFile} label="Airfoil" />}
            {inputMode === "compare" && (
              <div className="grid grid-2">
                <AirfoilPicker value={fileA} onChange={setFileA} label="Airfoil A" idPrefix="a" />
                <AirfoilPicker value={fileB} onChange={setFileB} label="Airfoil B" idPrefix="b" />
              </div>
            )}
            {inputMode === "batch" && (
              <>
                <FileDrop multiple files={batchFiles} onFiles={onBatchFiles} label="Drop up to 10 airfoil .dat files" />
                {batchNote && <div className="caption">{batchNote}</div>}
                <div className="caption">Batch runs every file at α = {alpha}°. AOA sweep and visualisations are off in batch mode.</div>
              </>
            )}
            {inputMode === "compare" && <div className="caption">Both airfoils run at the same Re, α and NCrit. AOA sweep is off in compare mode.</div>}

            <div className="btn-row">
              <button className="btn" onClick={run} disabled={!hasInput || running || status === "unavailable"}>{btnLabel}</button>
              {running && <button className="btn btn-secondary" onClick={() => abortRef.current?.abort()}>Cancel</button>}
            </div>
            {running && progress && (progress.value > 0 || sweepActive || inputMode === "batch"
              ? <Progress value={progress.value}>{progress.text}</Progress> : <Spinner>{progress.text}</Spinner>)}
            {error && <Alert kind="error">❌ {error}</Alert>}
          </div>

          <div style={{ marginTop: 24 }}>
            {result?.kind === "single" && <SingleResult res={result.res} p={result.p} />}
            {result?.kind === "sweep" && <SweepResult rows={result.rows} first={result.first} p={result.p} />}
            {result?.kind === "batch" && <BatchResult rows={result.rows} p={result.p} />}
            {result?.kind === "compare" && <CompareResult a={result.a} b={result.b} p={result.p} />}
            {!result && !running && (
              hasInput ? <Alert kind="info">⚙️ Parameters set. Click <strong>{btnLabel.replace("🚀 ", "")}</strong> to start.</Alert> : (
                <div className="card">
                  <h3 style={{ fontSize: 16, marginBottom: 12 }}>🎓 Quick start</h3>
                  <div className="grid grid-2">
                    <div>
                      <p><strong style={{ color: "var(--text)" }}>1. Get an airfoil file</strong></p>
                      <p className="caption">Pick an example above, or download a .dat from the{" "}
                        <a href="https://m-selig.ae.illinois.edu/ads/coord_database.html" target="_blank" rel="noreferrer">UIUC database</a>{" "}
                        (e.g. search "NACA 4412").</p>
                    </div>
                    <div>
                      <p><strong style={{ color: "var(--text)" }}>2. Set parameters</strong></p>
                      <p className="caption">Choose the Reynolds number and angle of attack on the left, then run.</p>
                    </div>
                  </div>
                </div>
              )
            )}
          </div>
        </main>
      </div>
      <Footer />
    </>
  );
}
