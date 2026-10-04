import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";
import StatusBanner from "../components/StatusBanner.jsx";
import AirfoilPicker from "../components/AirfoilPicker.jsx";
import CpEditor from "../components/CpEditor.jsx";
import {
  Alert, Checkbox, FileDrop, Metric, NumberField, Popover, Progress, Segmented, SliderField, Spinner, TimedProgress,
} from "../components/ui.jsx";
import Plot, { chartLayout, hline } from "../lib/Plot.jsx";
import { postForm } from "../lib/http.js";
import { downloadText, readFileText } from "../lib/files.js";
import { CpFileError, curveTargetCl, curveToDat, interp, parseCpFile, resampleForEditor } from "../lib/cpParser.js";
import { useBackendStatus } from "../useBackendStatus.js";
import { BACKEND_URL, COLORS } from "../config.js";

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36);
}

const baselineCache = new Map();

function ElapsedSeconds() {
  const [t, setT] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const id = setInterval(() => setT(Math.floor((performance.now() - start) / 1000)), 500);
    return () => clearInterval(id);
  }, []);
  return <> · {t} s</>;
}

function CpFileHelp() {
  return (
    <div className="help-text">
      <p><strong>What your Cp file needs</strong></p>
      <ul>
        <li><strong>Columns:</strong> <code>x  Cp</code>, or <code>x  y  Cp</code>. Spaces, tabs, commas or semicolons all
          work, and comment/header lines are skipped. A header naming the columns (e.g. <code>x, y, Cp</code>) lets any
          column order work.</li>
        <li><strong>Which surface is which</strong>, one of:
          <ol>
            <li>one continuous loop: trailing edge → upper surface → leading edge → lower surface → trailing edge
              (XFOIL's <code>CPWR</code> output is already like this),</li>
            <li>a <code>y</code> column, or</li>
            <li>two blocks (upper, then lower) separated by a blank line. A line saying <code>upper</code> or{" "}
              <code>lower</code> above each block makes it certain.</li>
          </ol>
          Always check the preview. If the surfaces are the wrong way round, tick <strong>Swap upper/lower</strong>.</li>
        <li><strong>x</strong> is the position along the chord, not the distance along the surface. Chord fractions,
          percent or mm are all fine; x is rescaled to 0–1.</li>
        <li><strong>Cp, not pressure:</strong> Cp = (p − p∞) / (½ρV²), suction negative. Not pressure in Pa, and not −Cp
          (the upside-down way Cp is often plotted).</li>
        <li><strong>Same conditions:</strong> set the <strong>angle of attack</strong> and <strong>Reynolds number</strong>{" "}
          on the left to the ones your data was measured or computed at. The design is solved and checked there.</li>
        <li><strong>Low speed only:</strong> the design assumes incompressible flow. Data taken above about Mach 0.3
          won't match exactly.</li>
        <li><strong>Resolution:</strong> up to 500 points per surface are used as-is. Include several points in the
          first 5% of chord, where the suction peak is; sparse data there makes lift and the nose shape less accurate.</li>
        <li><strong>Works with:</strong> XFOIL <code>CPWR</code>, XFLR5 Cp exports (the viscous <code>Cpv</code> column is
          used), SU2 <code>surface_flow.csv</code> (<code>Pressure_Coefficient</code>), spreadsheets saved as CSV, and
          curves downloaded from this page.</li>
      </ul>
    </div>
  );
}

const xyTrace = (pts, name, color, { line = {}, ...rest } = {}) => ({
  x: pts.map((p) => p[0]), y: pts.map((p) => p[1]), name, mode: "lines",
  line: { color, width: 3, ...line }, ...rest,
});

function Results({ result, stale }) {
  const fit = result.fit || {};
  const co = result.coefficients || {};
  const verified = result.verification_succeeded;
  const tu = result.target_cp_upper;
  const tl = result.target_cp_lower;
  const ru = result.result_cp_upper;
  const rl = result.result_cp_lower;

  const cpData = useMemo(() => {
    const d = [
      xyTrace(tu, "Target (upper)", COLORS.c2, { line: { width: 2, dash: "dot" } }),
      xyTrace(tl, "Target (lower)", COLORS.c5, { line: { width: 2, dash: "dot" } }),
    ];
    if (ru?.length) d.push(xyTrace(ru, "Achieved (upper)", COLORS.c2), xyTrace(rl, "Achieved (lower)", COLORS.c5));
    return d;
  }, [tu, tl, ru, rl]);
  const cpLayout = useMemo(() => chartLayout({ xTitle: "x/c", yTitle: "Cp", reverseY: true }), []);

  const geomData = useMemo(() => [
    xyTrace(result.seed_coords, "Seed", COLORS.textFaint, { line: { width: 2, dash: "dash" } }),
    { ...xyTrace(result.new_coords, "Designed airfoil", COLORS.c2), fill: "toself", fillcolor: "rgba(0,255,255,0.12)" },
  ], [result]);
  const geomLayout = useMemo(() => chartLayout({ xTitle: "x/c", yTitle: "y/c", equal: true }), []);

  const hist = (result.history || []).filter((h) => h.viscous_rms !== null && h.viscous_rms !== undefined);
  const errData = useMemo(() => {
    if (!ru?.length) return null;
    const xs = Array.from({ length: 200 }, (_, i) => 0.005 + (0.99 * i) / 199);
    const col = (pts, k) => pts.map((p) => p[k]);
    const e = (t, r) => xs.map((x) => interp(x, col(t, 0), col(t, 1)) - interp(x, col(r, 0), col(r, 1)));
    return [
      { x: xs, y: e(tu, ru), mode: "lines", name: "Upper", line: { color: COLORS.c2, width: 2 } },
      { x: xs, y: e(tl, rl), mode: "lines", name: "Lower", line: { color: COLORS.c5, width: 2 } },
    ];
  }, [tu, tl, ru, rl]);
  const errLayout = useMemo(() => chartLayout({ xTitle: "x/c", yTitle: "ΔCp", height: 280, shapes: [hline(0)] }), []);
  const histData = useMemo(() => [{
    x: hist.map((h) => h.iteration), y: hist.map((h) => h.viscous_rms), mode: "lines+markers",
    line: { color: COLORS.c3, width: 3 }, name: "Viscous Cp rms",
  }], [result]);
  const histLayout = useMemo(() => {
    const l = chartLayout({ xTitle: "Viscous correction step", yTitle: "Cp rms vs target", height: 280, legend: false });
    l.xaxis.dtick = 1;
    return l;
  }, []);

  const coordsDat = "AEROLAB INVERSE DESIGN\n" + result.new_coords.map(([x, y]) => `${x.toFixed(6)} ${y.toFixed(6)}`).join("\n");

  return (
    <div className="stack-lg" style={{ marginTop: 24 }}>
      {stale && <Alert kind="info">Settings or seed changed since the last design. Press <strong>Generate airfoil</strong> to update the result.</Alert>}
      {(result.warnings || []).map((w, i) => <Alert key={i} kind="warn">{w}</Alert>)}
      <div className="grid grid-5">
        <Metric label="Target CL (curve)" value={result.target_cl.toFixed(4)} />
        {verified ? (
          <>
            <Metric label="Achieved CL (viscous)" value={co.CL.toFixed(4)}
              sub={`${co.CL - result.target_cl >= 0 ? "+" : ""}${(co.CL - result.target_cl).toFixed(4)} vs target`} />
            <Metric label="Achieved CD" value={co.CD.toFixed(5)} />
            <Metric label="Achieved CM" value={co.CM.toFixed(4)} />
            <Metric label="Cp match (rms)" value={(fit.viscous_rms ?? 0).toFixed(3)}
              help="Root-mean-square difference between the target and the achieved viscous Cp over the whole surface. Below ~0.03 is a close match." />
          </>
        ) : <Metric label="Inviscid CL (unverified)" value={result.inviscid_cl.toFixed(4)} />}
      </div>
      <p className="caption">
        Seed: {result.seed_name} · max thickness {(result.seed_max_thickness * 100).toFixed(1)}% →{" "}
        {(result.max_thickness * 100).toFixed(1)}% at x/c = {result.max_thickness_x.toFixed(2)} · {result.elapsed_seconds.toFixed(1)} s
      </p>
      <div className="grid grid-2">
        <Plot title="Target vs achieved Cp (viscous XFOIL)" data={cpData} layout={cpLayout} filename="inverse_cp" />
        <Plot title="Designed geometry vs seed" data={geomData} layout={geomLayout} filename="inverse_geometry" />
      </div>
      {hist.length > 0 && (
        <div className="grid grid-2">
          {errData ? <Plot title="Remaining Cp error (target − achieved)" data={errData} layout={errLayout} filename="inverse_error" /> : <div />}
          <Plot title="Convergence (each step = one viscous correction)" data={histData} layout={histLayout} filename="inverse_convergence" />
        </div>
      )}
      <div className="btn-row">
        <button className="btn" onClick={() => downloadText("inverse_design_airfoil.dat", coordsDat)}>⬇️ Download coordinates (.dat)</button>
        <Link className="btn btn-secondary" to="/analysis">Analyse it in Airfoil Analysis →</Link>
      </div>
    </div>
  );
}

export default function InverseDesign() {
  const status = useBackendStatus();
  useEffect(() => { document.title = "Inverse Design - AeroLab"; }, []);

  const [reynolds, setReynolds] = useState(500_000);
  const [alpha, setAlpha] = useState(0);
  const [ncrit, setNcrit] = useState(9);
  const [seed, setSeed] = useState(null);
  const [minThickness, setMinThickness] = useState(0);

  const [source, setSource] = useState("draw");
  const [override, setOverride] = useState(null); // curve loaded from a file into the editor
  const [baseline, setBaseline] = useState(null);
  const [baselineInfo, setBaselineInfo] = useState(null);
  const [baselineState, setBaselineState] = useState("idle"); // idle | loading | error
  const [baselineErr, setBaselineErr] = useState(null);
  const [curve, setCurve] = useState(null);

  const [cpFile, setCpFile] = useState(null); // { name, text }
  const [swap, setSwap] = useState(false);

  const [running, setRunning] = useState(false);
  // undefined = idle, null = server can't report progress, else {fraction, message}
  const [progress, setProgress] = useState(undefined);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [resultKey, setResultKey] = useState(null);

  const seedHash = seed ? hash(seed.content) : "";
  const settingsKey = `${reynolds}|${alpha}|${ncrit}|${seed?.name || ""}|${seedHash}|${minThickness}`;

  // Seed's own Cp at the chosen condition = the editor's starting curve.
  // Debounced so dragging the alpha slider doesn't fire a request per step.
  const reqId = useRef(0);
  useEffect(() => {
    if (override) return undefined;
    const key = hash(`${reynolds}|${alpha}|${ncrit}|${seedHash}`);
    const apply = (b) => {
      setBaseline({ key, x: b.x, upper: b.upper, lower: b.lower });
      setBaselineInfo(b);
      setBaselineState("idle");
    };
    if (baselineCache.has(key)) { apply(baselineCache.get(key)); return undefined; }
    const id = ++reqId.current;
    setBaselineState("loading");
    const t = setTimeout(async () => {
      try {
        const b = await postForm("/inverse_design/baseline/", { reynolds, alpha, ncrit },
          { file: seed ? { name: seed.name, content: seed.content } : null, timeoutMs: 90000, retries: 0 });
        baselineCache.set(key, b);
        if (id === reqId.current) apply(b);
      } catch (e) {
        if (id === reqId.current) { setBaselineState("error"); setBaselineErr(e.message); }
      }
    }, 600);
    return () => clearTimeout(t);
  }, [reynolds, alpha, ncrit, seedHash, override]);

  const parsed = useMemo(() => {
    if (!cpFile) return null;
    try {
      return { ok: true, ...parseCpFile(cpFile.text) };
    } catch (e) {
      return { ok: false, error: e instanceof CpFileError ? e.message : `Couldn't read this file (${e.message}).` };
    }
  }, [cpFile]);

  let targetUpper = null;
  let targetLower = null;
  if (source === "upload" && parsed?.ok) {
    [targetUpper, targetLower] = swap ? [parsed.lower, parsed.upper] : [parsed.upper, parsed.lower];
  } else if (source === "draw" && curve) {
    targetUpper = curve.target_cp_upper;
    targetLower = curve.target_cp_lower;
  }
  const targetCl = targetUpper ? curveTargetCl(targetUpper, targetLower, alpha) : null;

  const previewData = useMemo(() => {
    if (!targetUpper || source !== "upload") return null;
    return [
      { x: targetUpper.map((p) => p[0]), y: targetUpper.map((p) => p[1]), mode: "lines+markers", name: "Upper surface",
        line: { color: COLORS.c2, width: 2 }, marker: { size: 4 } },
      { x: targetLower.map((p) => p[0]), y: targetLower.map((p) => p[1]), mode: "lines+markers", name: "Lower surface",
        line: { color: COLORS.c5, width: 2 }, marker: { size: 4 } },
    ];
  }, [targetUpper, targetLower, source]);
  const previewLayout = useMemo(() => chartLayout({ xTitle: "x/c", yTitle: "Cp", height: 320, reverseY: true }), []);

  const editorBaseline = override || baseline;

  const loadIntoEditor = () => {
    const ov = resampleForEditor(targetUpper, targetLower);
    setOverride({ ...ov, key: `upload-${hash(cpFile.text)}-${swap ? 1 : 0}` });
    setSource("draw");
  };

  const onCpFiles = async (files) => {
    setSwap(false);
    if (!files.length) { setCpFile(null); return; }
    const f = files[0];
    if (f.size > 2 * 1024 * 1024) { setCpFile({ name: f.name, text: "\u0000" }); return; }
    setCpFile({ name: f.name, text: await readFileText(f) });
  };

  const generate = async () => {
    if (!targetUpper) { setError("⚠️ No target yet: draw one or upload a Cp file first."); return; }
    setRunning(true);
    setError(null);
    setProgress({ fraction: 0, message: "Sending the design to the solver" });
    // The server reports its real stage for this job id; poll it while the
    // design runs. If the server is too old to report progress, fall back to
    // the time-based bar.
    const jobId = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()).replace(/[^A-Za-z0-9]/g, "");
    let polling = true;
    const poll = async () => {
      while (polling) {
        try {
          const res = await fetch(`${BACKEND_URL}/inverse_design/progress/${jobId}`, { cache: "no-store" });
          if (res.status === 404) { setProgress(null); return; }
          if (res.ok) {
            const d = await res.json();
            if (polling) setProgress((prev) => ({
              fraction: Math.max(prev?.fraction || 0, d.fraction || 0),
              message: d.message || prev?.message,
            }));
          }
        } catch { /* keep trying */ }
        await new Promise((r) => setTimeout(r, 500));
      }
    };
    poll();
    try {
      const r = await postForm("/inverse_design/", {
        reynolds, alpha, ncrit, min_thickness_percent: minThickness,
        target_cp_upper: JSON.stringify(targetUpper), target_cp_lower: JSON.stringify(targetLower),
        job_id: jobId,
      }, { file: seed ? { name: seed.name, content: seed.content } : null, timeoutMs: 280000, retries: 0 });
      setResult(r);
      setResultKey(settingsKey);
    } catch (e) {
      setError(`❌ ${e.message}`);
      setResult(null);
    } finally {
      polling = false;
      setRunning(false);
      setProgress(undefined);
    }
  };

  return (
    <>
      <Logo />
      <CmapBar />
      <div className="tool-layout">
        <aside className="tool-side">
          <div className="panel-title">✏️ Inverse Design</div>
          <Link to="/choose" className="btn btn-secondary btn-block btn-sm">← Choose a tool</Link>
          <NumberField label="Reynolds number" value={reynolds} min={10_000} max={10_000_000} step={10_000}
            onChange={(v) => setReynolds(Math.round(v))} />
          <SliderField label="Angle of attack" value={alpha} min={-10} max={20} step={0.5} onChange={setAlpha}
            format={(v) => `${v}°`} help="The condition the target curve is drawn for and the design is verified at." />
          <SliderField label="NCrit" value={ncrit} min={0.1} max={14} step={0.1} onChange={setNcrit}
            format={(v) => v.toFixed(1)} help="Transition sensitivity (9 = typical clean flow)." />
          <AirfoilPicker value={seed} onChange={setSeed} label="Seed airfoil (optional)" defaultLabel="NACA 0012 (default)" />
          <div className="caption">Starting from: <strong>{seed?.name || "NACA 0012 (default)"}</strong></div>
          <NumberField label="Minimum thickness (% chord)" value={minThickness} min={0} max={40} step={0.5}
            onChange={setMinThickness}
            help="Keeps the design at least this thick (e.g. for a spar). 0 = only stop the surfaces from crossing." />
          <button className="btn btn-block" onClick={generate} disabled={running || status === "unavailable"}>
            {running ? "Designing…" : "🚀 Generate airfoil"}
          </button>
          <div className="card help-card">
            <strong style={{ color: "var(--text)" }}>How it works.</strong> Draw the pressures you want (the curve starts
            as the seed airfoil's own pressure distribution) or upload a Cp file. AeroLab then reshapes the seed until its
            viscous Cp matches as closely as possible (SU2-style Cp matching over the whole surface), and verifies the
            result with XFOIL.
          </div>
        </aside>

        <main className="tool-main">
          <h1 className="tool-h1">🎨 Target pressure distribution</h1>
          <p className="tool-sub">Draw it or upload it, then generate an airfoil that produces it</p>
          <StatusBanner status={status} />

          <div className="card stack" style={{ marginTop: 16 }}>
            <Segmented value={source} onChange={setSource} ariaLabel="Target source"
              options={[["draw", "✏️ Draw it"], ["upload", "📄 Upload a Cp file"]]} />

            {source === "upload" && (
              <>
                <div className="upload-row">
                  <div style={{ flex: 1 }}>
                    <FileDrop accept=".dat,.txt,.csv" files={cpFile ? [cpFile] : []} onFiles={onCpFiles}
                      label="Drop a Cp file here" hint="x and Cp (or x, y, Cp) for both surfaces · .dat .txt .csv" />
                  </div>
                  <Popover trigger="ℹ️ File format"><CpFileHelp /></Popover>
                </div>
                {!cpFile && (
                  <Alert kind="info">Upload a file with the pressure distribution you want the airfoil to have. Open{" "}
                    <strong>ℹ️ File format</strong> first. The angle of attack and Reynolds number on the left must match your data.</Alert>
                )}
                {parsed && !parsed.ok && <Alert kind="error">Couldn't use this file: {parsed.error}</Alert>}
                {parsed?.ok && (
                  <>
                    <Checkbox label="Swap upper/lower" checked={swap} onChange={setSwap}
                      help="Tick if the preview shows the surfaces the wrong way round." />
                    <div className="caption">Read as <strong>{parsed.format}</strong>: {targetUpper.length} upper-surface and{" "}
                      {targetLower.length} lower-surface points.</div>
                    {parsed.notes.map((n, i) => <div key={i} className="caption">• {n}</div>)}
                    {parsed.upper_guessed && !swap && (
                      <div className="caption">⚠️ Upper/lower was assigned by the usual file order, not from the data. The upper
                        surface is normally the one with more suction (more negative Cp) at positive angles of attack.</div>
                    )}
                    {parsed.warnings.map((w, i) => <Alert key={i} kind="warn">{w}</Alert>)}
                    <Plot title="Uploaded target (check the surfaces are the right way round)" data={previewData}
                      layout={previewLayout} filename="uploaded_target_cp" />
                    <div>
                      <button className="btn btn-secondary btn-sm" onClick={loadIntoEditor}
                        title="Copies this curve into the drag editor (resampled to its 41 points per surface, which loses some detail near the leading edge).">
                        ✏️ Load into the editor to tweak it</button>
                    </div>
                  </>
                )}
              </>
            )}
            <div style={{ display: source === "draw" ? "contents" : "none" }}>
                {override ? (
                  <div className="btn-row">
                    <span className="caption">The editor holds the curve you loaded from a file.</span>
                    <button className="btn btn-secondary btn-sm" onClick={() => setOverride(null)}>↺ Start from the seed's Cp instead</button>
                  </div>
                ) : baselineState === "loading" ? <Spinner>Loading the seed's pressure distribution…</Spinner>
                  : baselineState === "error" ? <Alert kind="warn">Couldn't load the seed's pressure distribution ({baselineErr}). Showing the default curve.</Alert>
                    : null}
                <CpEditor baseline={editorBaseline} onChange={setCurve} />
                {curve && (
                  <div>
                    <button className="btn btn-secondary btn-sm" title="Saves the curve so you can upload it again later (XFOIL order: x, Cp)."
                      onClick={() => downloadText("aerolab_target_cp.dat", curveToDat(curve.target_cp_upper, curve.target_cp_lower, alpha, reynolds))}>
                      ⬇️ Download this curve (.dat)</button>
                  </div>
                )}
            </div>

            <div className="grid grid-2">
              {targetCl !== null && <Metric label="Target CL (from your curve)" value={targetCl.toFixed(4)}
                help="Lift implied by the target curve itself: the area between the lower- and upper-surface Cp curves." />}
              {baselineInfo?.CL != null && !override && (
                <Metric label={baselineInfo.source === "xfoil_viscous" ? "Seed CL (XFOIL viscous)" : "Seed CL (inviscid)"}
                  value={(Math.round(baselineInfo.CL * 1e4) / 1e4 + 0).toFixed(4)} />
              )}
            </div>
            {running && (
              progress === null ? (
                <TimedProgress expected={60} label="Designing the airfoil" />
              ) : (
                <Progress value={progress?.fraction || 0}>
                  {progress?.message || "Designing the airfoil"} · {Math.round((progress?.fraction || 0) * 100)}%
                  <ElapsedSeconds />
                </Progress>
              )
            )}
            {error && <Alert kind="error">{error}</Alert>}
          </div>

          {result && <Results result={result} stale={resultKey !== settingsKey} />}
        </main>
      </div>
      <Footer />
    </>
  );
}
