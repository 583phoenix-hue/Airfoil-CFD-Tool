import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";
import { COLORS } from "../config.js";

const MODES = [
  { icon: "📐", accent: COLORS.c2, title: "Analyze Airfoil", to: "/analysis", cta: "Analyze an airfoil →",
    desc: "Upload a coordinate file or pick a bundled example. Get lift, drag, moment coefficients, and pressure distribution from XFOIL." },
  { icon: "✏️", accent: COLORS.c5, title: "Inverse Design", to: "/inverse-design", cta: "Design an airfoil →",
    desc: "Draw the pressure distribution you want. AeroLab generates an airfoil shape to match it, then verifies the result with a real analysis." },
  { icon: "〰️", accent: COLORS.c6, title: "Aeroelasticity", to: "/aeroelasticity", cta: "Explore aeroelasticity →",
    desc: "Check how a flexible wing responds to airspeed: torsional divergence, control reversal, and flutter, computed from real airfoil data." },
];

export default function ChooseMode() {
  useEffect(() => { document.title = "Choose a Tool - AeroLab"; }, []);
  return (
    <>
      <Logo />
      <CmapBar />
      <Link className="btn btn-secondary" to="/">← Home</Link>

      <section className="center" style={{ maxWidth: 720, margin: "0 auto" }}>
        <h1 style={{ fontSize: "clamp(28px,4.5vw,44px)", lineHeight: 1.1, margin: "24px 0 4px" }}>What do you want to do?</h1>
        <p style={{ fontSize: 16, maxWidth: 640, margin: "0 auto 40px", lineHeight: 1.6 }}>
          Analyze an existing airfoil's aerodynamics, design a new one from a target pressure distribution, or
          check how a flexible wing behaves in flight.
        </p>
      </section>

      <div className="grid grid-3" style={{ maxWidth: 1100, margin: "0 auto" }}>
        {MODES.map((m) => (
          <div key={m.title} className="stack" style={{ gap: 16 }}>
            <div className="card center" style={{ padding: "36px 28px", flex: 1 }}>
              <div className="mode-icon" style={{ background: `${m.accent}20`, color: m.accent }}>{m.icon}</div>
              <div style={{ fontFamily: "var(--font-head)", fontSize: 20, fontWeight: 600, color: "var(--text)", marginBottom: 10 }}>{m.title}</div>
              <p style={{ fontSize: 14, lineHeight: 1.6 }}>{m.desc}</p>
            </div>
            <Link className="btn btn-block" to={m.to}>{m.cta}</Link>
          </div>
        ))}
      </div>

      <Footer />
    </>
  );
}
