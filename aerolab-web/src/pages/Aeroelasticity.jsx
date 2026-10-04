import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";
import AeroArt from "../components/AeroArt.jsx";

export const MODULES = {
  divergence: {
    name: "Static Divergence",
    tagline: "Find the airspeed where a wing twists itself apart",
    description:
      "As airspeed rises, aerodynamic lift twists a flexible wing further, which increases lift further still. Below "
      + "the divergence speed this settles to a stable equilibrium; at and above it, no stable twist exists and the wing "
      + "diverges. Uses the airfoil's real, converged XFOIL lift and moment curves, traces the exact equilibrium twist at "
      + "every airspeed, and compares the result with classical linear divergence theory.",
    tags: ["torsional stiffness", "elastic axis", "XFOIL polar"],
  },
  reversal: {
    name: "Control Reversal",
    tagline: "Find the airspeed where a control surface stops working",
    description:
      "A flap deflection creates lift directly, but also twists the wing enough to partly cancel that lift. As airspeed "
      + "rises, the twist-induced loss grows faster than the direct gain, until the control's net effect hits zero and "
      + "reverses. Flap lift and moment are measured by deflecting the flap in XFOIL (or taken from thin-airfoil theory), "
      + "and the result is checked against the classical linear reversal formula.",
    tags: ["flap effectiveness", "XFOIL flap", "elastic axis"],
  },
  flutter: {
    name: "Flutter",
    tagline: "Find the airspeed where wing oscillation becomes self-sustaining",
    description:
      "Coupled pitch and plunge motion can extract energy from the airflow faster than structural damping removes it, "
      + "growing without bound. Solved with exact unsteady (Theodorsen) aerodynamics by the p-k method, cross-checked "
      + "against a Jones state-space model and time-domain simulation, and shown as the classic V-g and V-f flutter diagrams.",
    tags: ["pitch + plunge", "unsteady aerodynamics", "V-g method"],
  },
};
export const MODULE_ORDER = ["divergence", "reversal", "flutter"];

function ModuleDialog({ onClose }) {
  const navigate = useNavigate();
  const [sel, setSel] = useState(() => sessionStorage.getItem("aero_selected_module") || "divergence");
  const m = MODULES[sel] || MODULES.divergence;
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  const pick = (k) => { setSel(k); try { sessionStorage.setItem("aero_selected_module", k); } catch { /* ignore */ } };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="mod-title"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="card modal modal-lg">
        <h3 id="mod-title" style={{ marginBottom: 18 }}>Select an aeroelasticity module</h3>
        <div className="module-dialog">
          <div className="module-list" role="radiogroup" aria-label="Module">
            {MODULE_ORDER.map((k) => (
              <button key={k} type="button" role="radio" aria-checked={sel === k}
                className={`module-option ${sel === k ? "active" : ""}`} onClick={() => pick(k)}
                onDoubleClick={() => navigate(`/aeroelasticity/${k}`)}>
                <span className="radio-dot" aria-hidden="true" />{MODULES[k].name}
              </button>
            ))}
          </div>
          <div>
            <div className="art-box"><AeroArt module={sel} /></div>
            <div style={{ fontFamily: "var(--font-head)", fontSize: 19, fontWeight: 600, color: "var(--text)", marginBottom: 4 }}>{m.name}</div>
            <div style={{ fontSize: 13, marginBottom: 12 }}>{m.tagline}</div>
            <p style={{ fontSize: 14, lineHeight: 1.65, marginBottom: 14 }}>{m.description}</p>
            <div className="tags">{m.tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>
          </div>
        </div>
        <hr className="hr" />
        <div className="btn-row" style={{ justifyContent: "space-between" }}>
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn" onClick={() => navigate(`/aeroelasticity/${sel}`)}>Run analysis →</button>
        </div>
      </div>
    </div>
  );
}

export default function Aeroelasticity() {
  const [open, setOpen] = useState(false);
  useEffect(() => { document.title = "Aeroelasticity - AeroLab"; }, []);
  return (
    <>
      <Logo />
      <CmapBar />
      <Link to="/choose" className="btn btn-secondary btn-sm">← Choose a tool</Link>
      <section className="center" style={{ maxWidth: 640, margin: "0 auto" }}>
        <h1 style={{ fontSize: "clamp(28px,4.5vw,44px)", lineHeight: 1.1, margin: "24px 0 8px" }}>Aeroelasticity</h1>
        <p style={{ fontSize: 16, lineHeight: 1.6, marginBottom: 40 }}>
          Check how a flexible wing behaves as airspeed rises: divergence, control reversal, and flutter, computed from
          real airfoil data.
        </p>
      </section>
      <div style={{ maxWidth: 520, margin: "0 auto" }}>
        <div className="card center" style={{ padding: "40px 28px" }}>
          <div className="mode-icon" style={{ background: "#ff000020", color: "var(--c6)" }}>〰️</div>
          <div style={{ fontFamily: "var(--font-head)", fontSize: 19, fontWeight: 600, color: "var(--text)", marginBottom: 10 }}>
            Three modules available</div>
          <p style={{ fontSize: 14, lineHeight: 1.6 }}>Static divergence, control reversal, and flutter. Pick one to see what it
            computes and run it on your wing's structural and aerodynamic properties.</p>
        </div>
        <button className="btn btn-block" style={{ marginTop: 16 }} onClick={() => setOpen(true)}>Select module →</button>
        <div className="grid grid-3" style={{ marginTop: 24 }}>
          {MODULE_ORDER.map((k) => (
            <Link key={k} to={`/aeroelasticity/${k}`} className="mini-module">
              <div className="art-box" style={{ marginBottom: 8 }}><AeroArt module={k} /></div>
              <span>{MODULES[k].name}</span>
            </Link>
          ))}
        </div>
      </div>
      {open && <ModuleDialog onClose={() => setOpen(false)} />}
      <Footer />
    </>
  );
}
