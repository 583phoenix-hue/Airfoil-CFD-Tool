import { Link, Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";

export function Logo() {
  return (
    <Link to="/" style={{ display: "inline-flex", alignItems: "center", gap: 10, fontFamily: "var(--font-head)",
      fontWeight: 600, fontSize: 17, color: "var(--text)", textDecoration: "none", paddingTop: "0.5rem" }}>
      <span aria-hidden="true" style={{ width: 26, height: 26, borderRadius: 6, display: "flex", alignItems: "center",
        justifyContent: "center", fontSize: 13, color: "#fff",
        background: "linear-gradient(135deg, var(--c1), var(--c3), var(--c6))" }}>✈</span>
      <span>AeroLab</span>
    </Link>
  );
}

export function CmapBar() {
  return <div className="cmap-bar" />;
}

export function Footer({ text = "Powered by XFOIL · For educational use · AeroLab © 2026" }) {
  return (
    <footer style={{ marginTop: 48 }}>
      <CmapBar />
      <div className="mono center" style={{ color: "var(--text-faint)", fontSize: 12, paddingBottom: "2rem" }}>{text}</div>
    </footer>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  // Tool pages get a wider frame for the side panel + charts; everything
  // else stays at a comfortable reading width.
  const wide = /^\/(analysis|inverse-design)/.test(pathname);
  return (
    <div className={wide ? "page page-wide" : "page"}>
      <Outlet />
    </div>
  );
}
