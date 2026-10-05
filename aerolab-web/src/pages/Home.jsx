import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";
import { useBackendStatus } from "../useBackendStatus.js";
import { getAnalysisCount } from "../api.js";
import { COLORS } from "../config.js";
import { localXfoilSupported } from "../lib/xfoil/xfoilClient.js";

const FEATURES = [
  ["🎯", "Accurate analysis", "Industry-standard XFOIL panel method for precise aerodynamic predictions.", COLORS.c2],
  ["⚡", "Fast results", "Robust coordinate parsing means fewer failed runs and less waiting.", COLORS.c3],
  ["📊", "Visual insights", "Interactive pressure distribution, geometry, and wind tunnel visualization.", COLORS.c5],
];

const STEPS = [
  ["01", "Upload", "Airfoil coordinate file (.dat/.txt) from UIUC or Airfoil Tools, or pick a bundled example."],
  ["02", "Configure", "Set Reynolds number, angle of attack, NCrit, and viscous/inviscid mode."],
  ["03", "Analyze", "Get lift, drag, moment coefficients, and detailed pressure distributions."],
];

function SuspendedModal({ onClose }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="susp-title">
      <div className="card modal stack">
        <h3 id="susp-title">🛠️ Solver Temporarily Unavailable</h3>
        <div className="alert alert-warn"><strong style={{ color: "var(--text)" }}>Scheduled Maintenance Underway</strong></div>
        <p style={{ lineHeight: 1.6 }}>
          The aerodynamic solver is undergoing scheduled maintenance. Please check again shortly.
        </p>
        <p style={{ lineHeight: 1.6 }}>
          You can still browse the site — analysis functionality will return shortly!
        </p>
        <button className="btn btn-block" onClick={onClose}>Got it</button>
      </div>
    </div>
  );
}

export default function Home() {
  const backendStatus = useBackendStatus();
  // Analysis and aeroelasticity run XFOIL in the browser, so the site is
  // usable even when the server is asleep or down; only browsers that can't
  // run it (no WebAssembly) still depend on the server's status here.
  const local = localXfoilSupported();
  const status = local ? "online" : backendStatus;
  const [count, setCount] = useState(undefined);
  const [popupDismissed, setPopupDismissed] = useState(() => sessionStorage.getItem("suspension_popup_shown") === "1");

  useEffect(() => {
    document.title = "AeroLab - Airfoil Analysis Tool";
    let alive = true;
    getAnalysisCount().then((c) => alive && setCount(c));
    return () => { alive = false; };
  }, [backendStatus === "online"]); // re-read the counter once the server is up

  const closePopup = () => {
    try { sessionStorage.setItem("suspension_popup_shown", "1"); } catch { /* private mode */ }
    setPopupDismissed(true);
  };

  return (
    <>
      <Logo />
      <CmapBar />
      {status === "unavailable" && !popupDismissed && <SuspendedModal onClose={closePopup} />}

      <section className="center" style={{ maxWidth: 720, margin: "0 auto" }}>
        <h1 style={{ fontSize: "clamp(32px,5vw,52px)", lineHeight: 1.1, margin: "20px 0 4px" }}>
          Welcome to <span className="gradient-text">AeroLab</span>
        </h1>
        <p style={{ fontSize: 16, maxWidth: 520, margin: "0 auto 32px", lineHeight: 1.6 }}>
          Upload a .dat, get lift, drag, and pressure distribution back in seconds — powered by XFOIL,
          with a parser built to handle real-world UIUC coordinate file quirks automatically.
        </p>
      </section>

      <div className="stack" style={{ maxWidth: 420, margin: "16px auto 0" }}>
        {status === "online" && (
          <Link className="btn btn-block" to="/choose">🚀 Analyze airfoil</Link>
        )}
        {status === "checking" && (
          <button className="btn btn-block" disabled>Checking the solver…</button>
        )}
        {status === "unavailable" && (
          <>
            <div className="alert alert-error">🛠️ Maintenance ongoing</div>
            <div className="alert alert-info">Wind tunnel undergoing maintenance for a better experience. Check back soon!</div>
            <button className="btn btn-block" disabled>Analyze airfoil (offline)</button>
          </>
        )}
        {status === "waking" && (
          <>
            <div className="alert alert-warn">⏳ Solver waking up…</div>
            <div className="alert alert-info">
              The aerodynamic solver is starting up due to inactivity (Render free tier, ~30–60s).
              This page will enable the button automatically when it's ready.
            </div>
            <button className="btn btn-block" disabled>Analyze airfoil (starting…)</button>
          </>
        )}
        <Link className="btn btn-block btn-secondary" to="/about">📖 About AeroLab</Link>
      </div>

      <div className="card center" style={{ maxWidth: 560, margin: "32px auto 0" }}>
        <div style={{ fontSize: 12.5, color: "var(--text-faint)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
          Total analyses performed
        </div>
        <div className="mono" style={{ fontSize: 36, fontWeight: 500, color: "var(--text)" }}>
          {count === undefined ? "…" : count === null ? "—" : count.toLocaleString()}
        </div>
        <div style={{ fontSize: 12, color: "var(--text-faint)", marginTop: 4 }}>
          {count === null ? "Counter unavailable right now" : "Airfoils analyzed by aerospace enthusiasts worldwide"}
        </div>
      </div>

      <h2 style={{ marginTop: 48, marginBottom: 16 }}>Features</h2>
      <div className="grid grid-3">
        {FEATURES.map(([icon, title, desc, accent]) => (
          <div className="card" key={title}>
            <div className="feature-icon" style={{ background: `${accent}20`, color: accent }}>{icon}</div>
            <div style={{ fontSize: 16, fontWeight: 500, color: "var(--text)", marginBottom: 8 }}>{title}</div>
            <div style={{ fontSize: 14, lineHeight: 1.6 }}>{desc}</div>
          </div>
        ))}
      </div>

      <h2 style={{ marginTop: 48, marginBottom: 16 }}>How it works</h2>
      <div className="grid grid-3">
        {STEPS.map(([n, title, desc]) => (
          <div className="card" key={n}>
            <div className="mono" style={{ fontSize: 11, color: "var(--text-faint)", marginBottom: 8 }}>{n}</div>
            <div style={{ fontSize: 15, fontWeight: 500, color: "var(--text)", marginBottom: 6 }}>{title}</div>
            <div style={{ fontSize: 13, lineHeight: 1.6 }}>{desc}</div>
          </div>
        ))}
      </div>

      <Footer />
    </>
  );
}
