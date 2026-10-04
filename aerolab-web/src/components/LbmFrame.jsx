import { useEffect, useMemo, useRef, useState } from "react";

// The wind tunnels are the same self-contained WebGL2 pages the Streamlit app
// embeds (public/lbm/*.html). They're loaded once, the airfoil coordinates are
// substituted into their %%TOKENS%%, and the result goes into a srcdoc iframe.
// srcdoc iframes are same-origin, so the dual tunnel's "Enlarge" button can
// still grow its own frame to full screen (window.frameElement), as before.
//
// LBM_VERSION picks the wind tunnel: "v2" (640×320, Smagorinsky, GPU trails,
// smoke view, enhanced eddies) or "v1" (the original 320×160 version, kept
// in public/lbm/*_v1.html). Change it here to switch back.
const LBM_VERSION = "v2";
const cache = {};
function loadTemplate(kind) {
  const name = LBM_VERSION === "v1" ? `${kind}_v1` : kind;
  if (!cache[name]) {
    cache[name] = fetch(`/lbm/${name}.html`).then((r) => {
      if (!r.ok) throw new Error("template missing");
      return r.text();
    });
  }
  return cache[name];
}

const coordsJson = (coords) =>
  JSON.stringify((coords || []).map(([x, y]) => [Math.round(x * 1e6) / 1e6, Math.round(y * 1e6) / 1e6]));

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export default function LbmFrame({ coords, name, coordsB, nameB }) {
  const dual = coordsB !== undefined;
  const [template, setTemplate] = useState(null);
  const [error, setError] = useState(false);
  const [height, setHeight] = useState(dual ? 760 : 700);
  const frame = useRef(null);
  const observer = useRef(null);
  useEffect(() => () => observer.current?.disconnect(), []);

  // Size the frame to its content (no dead space under the controls). Skipped
  // while the dual tunnel's Enlarge overlay has pinned the frame full screen.
  const onLoad = () => {
    const f = frame.current;
    const doc = f?.contentDocument;
    if (!doc) return;
    const measure = () => {
      if (f.style.position === "fixed") return;
      const h = Math.ceil(doc.body.getBoundingClientRect().height) + 16;
      if (h > 200) setHeight(h);
    };
    observer.current?.disconnect();
    observer.current = new ResizeObserver(measure);
    observer.current.observe(doc.body);
    measure();
  };

  useEffect(() => {
    let alive = true;
    loadTemplate(dual ? "dual" : "single").then((t) => alive && setTemplate(t)).catch(() => alive && setError(true));
    return () => { alive = false; };
  }, [dual]);

  const html = useMemo(() => {
    if (!template) return null;
    if (!dual) {
      return template
        .replaceAll("%%USER_COORDS%%", coordsJson(coords))
        .replaceAll("%%USER_NAME%%", JSON.stringify(name || "Uploaded airfoil"));
    }
    const nA = name || "Airfoil A";
    const nB = nameB || "Airfoil B";
    return template
      // visible labels: plain text (the JS constants below need JSON strings)
      .replace('<div class="lbm-dual-name">%%USER_NAME_A%%</div>', `<div class="lbm-dual-name">${escapeHtml(nA)}</div>`)
      .replace('<div class="lbm-dual-name">%%USER_NAME_B%%</div>', `<div class="lbm-dual-name">${escapeHtml(nB)}</div>`)
      .replaceAll("%%USER_COORDS_A%%", coordsJson(coords))
      .replaceAll("%%USER_NAME_A%%", JSON.stringify(nA))
      .replaceAll("%%USER_COORDS_B%%", coordsJson(coordsB))
      .replaceAll("%%USER_NAME_B%%", JSON.stringify(nB));
  }, [template, dual, coords, name, coordsB, nameB]);

  if (error) return <div className="alert alert-error">⚠️ The wind-tunnel visualisation couldn't be loaded.</div>;
  if (!html) return <div className="lbm-placeholder" style={{ height: dual ? 760 : 700 }}>Loading wind tunnel…</div>;
  return (
    <iframe
      title={dual ? "Side-by-side wind tunnel" : "Interactive wind tunnel"}
      className="lbm-frame"
      ref={frame}
      srcDoc={html}
      onLoad={onLoad}
      style={{ height }}
      allow="fullscreen"
    />
  );
}
