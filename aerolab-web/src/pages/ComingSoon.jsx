import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";

// Temporary page for tools that haven't been ported from the Streamlit app yet.
const CLASSIC_URL = import.meta.env.VITE_CLASSIC_APP_URL || "https://aerolab-app.onrender.com";

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
          This tool is still being moved to the new site. Until then it's available on the classic AeroLab app.
        </p>
        <a className="btn" href={CLASSIC_URL}>Open the classic app →</a>
      </div>
      <Footer />
    </>
  );
}
