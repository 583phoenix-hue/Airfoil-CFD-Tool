import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CmapBar, Footer } from "../components/Layout.jsx";

const FEATURES_LEFT = [
  ["🎯", "Accurate predictions", "Powered by XFOIL, the most widely-used and validated panel method code in aerospace engineering."],
  ["📊", "Visual analytics", "Airfoil geometry, pressure distributions, boundary layer data, and an interactive wind tunnel."],
  ["🌐", "Cloud-based", "No installation required. Access from any device with a web browser."],
];
const FEATURES_RIGHT = [
  ["⚙️", "Flexible configuration", "Reynolds numbers from 10,000 to 10,000,000 and angles of attack from -20° to +25°."],
  ["💾", "Export results", "Download pressure distribution and boundary-layer data as CSV for further analysis."],
  ["⚖️", "Compare mode", "Two airfoils side by side, with a shared interactive wind tunnel."],
];
const STEPS = [
  ["🔍", "1. Get airfoil data", "Download .dat files from UIUC or Airfoil Tools, or pick a bundled example."],
  ["⚙️", "2. Set parameters", "Choose Reynolds number, angle of attack, NCrit, and viscous/inviscid mode."],
  ["🚀", "3. Run analysis", "XFOIL runs server-side and returns results, typically in seconds."],
  ["📊", "4. View results", "Coefficients, pressure plots, wind tunnel visualization, and CSV export."],
];

function FeatureCard([icon, title, desc]) {
  return (
    <div className="card" key={title}>
      <div style={{ fontSize: 20, marginBottom: 8 }}>{icon}</div>
      <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text)", marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13, lineHeight: 1.6 }}>{desc}</div>
    </div>
  );
}

const strong = { color: "var(--text)" };

export default function About() {
  const [photoOk, setPhotoOk] = useState(true);
  useEffect(() => { document.title = "About - AeroLab"; }, []);

  return (
    <>
      <Link className="btn btn-secondary" to="/">← Back to home</Link>
      <div style={{ marginTop: 24 }}>
        <span className="eyebrow"><span className="eyebrow-dot" />The project</span>
      </div>
      <h1 style={{ marginTop: 16 }}>About AeroLab</h1>
      <CmapBar />

      <h2 className="section-title">What is AeroLab?</h2>
      <div className="card stack" style={{ gap: 12 }}>
        <p style={{ fontSize: 15, lineHeight: 1.7 }}>
          AeroLab is a web application designed to make airfoil aerodynamic analysis accessible to students,
          researchers, and aerospace enthusiasts. Built on the industry-standard XFOIL panel method solver, it
          predicts lift, drag, and pressure distributions for 2D airfoil sections.
        </p>
        <p style={{ fontSize: 15, lineHeight: 1.7 }}>
          Whether you're designing a model aircraft, studying aerospace engineering, or exploring computational
          fluid dynamics, AeroLab offers a way to run aerodynamic calculations without expensive software or
          high-performance computing.
        </p>
      </div>

      <h2 className="section-title">Key features</h2>
      <div className="grid grid-2">
        <div className="stack" style={{ gap: 14 }}>{FEATURES_LEFT.map(FeatureCard)}</div>
        <div className="stack" style={{ gap: 14 }}>{FEATURES_RIGHT.map(FeatureCard)}</div>
      </div>

      <h2 className="section-title">Technical details</h2>
      <div className="card">
        <h3 style={{ fontSize: 15, fontWeight: 500, marginBottom: 10 }}>XFOIL panel method</h3>
        <p style={{ fontSize: 14, marginBottom: 14, lineHeight: 1.7 }}>
          XFOIL is a design and analysis system for low Reynolds number subsonic isolated airfoils, developed by
          Professor Mark Drela at MIT. It combines:
        </p>
        <ul style={{ fontSize: 14, lineHeight: 1.8, paddingLeft: 20, marginBottom: 18 }}>
          <li><strong style={strong}>Panel method</strong> — inviscid flow solution using source and vortex panels</li>
          <li><strong style={strong}>Boundary layer analysis</strong> — viscous effects via integral formulation, with adjustable NCrit</li>
          <li><strong style={strong}>Transition prediction</strong> — natural transition modeling (e^N method)</li>
          <li><strong style={strong}>Wake modeling</strong> — accurate drag prediction through wake panel representation</li>
        </ul>
        <h3 style={{ fontSize: 15, fontWeight: 500, marginBottom: 10 }}>Platform architecture</h3>
        <ul style={{ fontSize: 14, lineHeight: 1.8, paddingLeft: 20, margin: 0 }}>
          <li><strong style={strong}>Frontend</strong> — React (static site, runs in your browser)</li>
          <li><strong style={strong}>Backend</strong> — FastAPI with XFOIL subprocess integration</li>
          <li><strong style={strong}>Coordinate parser</strong> — auto-repairs Lednicer/Selig format issues, winding order, duplicate points</li>
        </ul>
      </div>

      <h2 className="section-title">Developer</h2>
      <div style={{ maxWidth: 480, margin: "0 auto" }}>
        <div style={{ maxWidth: 220, margin: "0 auto 14px" }}>
          {photoOk ? (
            <img src="/developer.jpg" alt="Pranav Nathan" onError={() => setPhotoOk(false)}
                 style={{ width: "100%", borderRadius: 10, display: "block" }} />
          ) : (
            <div className="center" style={{ fontSize: 40 }} aria-hidden="true">👤</div>
          )}
        </div>
        <div className="card center">
          <div style={{ fontFamily: "var(--font-head)", fontSize: 20, fontWeight: 600, color: "var(--text)", marginBottom: 4 }}>Pranav Nathan</div>
          <div style={{ fontSize: 13, marginBottom: 16 }}>Aspiring aerospace engineer</div>
          <p style={{ fontSize: 14, lineHeight: 1.7, maxWidth: 420, margin: "0 auto 12px" }}>
            Passionate about computational fluid dynamics and aerospace design. AeroLab was built to make
            aerodynamic analysis tools accessible to students and educators worldwide.
          </p>
          <p style={{ fontSize: 13, color: "var(--text-faint)" }}>Aerodynamics · CFD · CAD · Research</p>
        </div>
      </div>

      <h2 className="section-title">How to use AeroLab</h2>
      <div className="grid grid-4">
        {STEPS.map(([icon, title, desc]) => (
          <div className="card center" key={title}>
            <div style={{ fontSize: 28, marginBottom: 10 }}>{icon}</div>
            <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)", marginBottom: 6 }}>{title}</div>
            <div style={{ fontSize: 12, lineHeight: 1.6 }}>{desc}</div>
          </div>
        ))}
      </div>

      <h2 className="section-title">Contact & support</h2>
      <div className="card stack">
        <p style={{ fontSize: 14, lineHeight: 1.7 }}>
          For questions, suggestions, or collaboration opportunities, please reach out through email at{" "}
          <a href="mailto:pranav09nathan@gmail.com">pranav09nathan@gmail.com</a>. This is an open educational project
          aimed at advancing aerospace education.
        </p>
        <p style={{ fontSize: 14, lineHeight: 1.7 }}>
          <strong style={strong}>Note:</strong> this tool is provided for educational purposes. For critical
          applications, always validate results with experimental data or higher-fidelity CFD methods.
        </p>
      </div>

      <Footer text="AeroLab © 2026 · Built with XFOIL · Advancing aerospace education, one airfoil at a time" />
    </>
  );
}
