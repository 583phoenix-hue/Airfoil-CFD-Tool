import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";

// Shown for a tool that is temporarily unavailable.
export default function ComingSoon({ title }) {
  useEffect(() => { document.title = `${title} - AeroLab`; }, [title]);
  return (
    <>
      <Logo />
      <CmapBar />
      <Link className="btn btn-secondary" to="/choose">← Choose a tool</Link>
      <div className="card center" style={{ maxWidth: 560, margin: "48px auto 0", padding: "36px 28px" }}>
        <h1 style={{ fontSize: 28, marginBottom: 12 }}>{title}</h1>
        <p style={{ fontSize: 15, lineHeight: 1.6, marginBottom: 20 }}>
          Coming soon. This tool is being upgraded so it runs faster, right in your browser.
        </p>
        <Link className="btn" to="/analysis">Analyze an airfoil instead →</Link>
      </div>
      <Footer />
    </>
  );
}
