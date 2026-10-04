// Shown on pages that need the solver when it isn't reachable yet.
export default function StatusBanner({ status }) {
  if (status === "online") return null;
  if (status === "checking") {
    return <div className="alert alert-info">Checking the solver…</div>;
  }
  if (status === "unavailable") {
    return (
      <div className="alert alert-error">
        <strong style={{ color: "var(--text)" }}>🛠️ Solver unavailable.</strong> The aerodynamic solver is
        under maintenance or has reached its monthly compute limit. You can still browse the site; analysis will
        return shortly.
      </div>
    );
  }
  return (
    <div className="alert alert-warn">
      <strong style={{ color: "var(--text)" }}>⏳ Solver waking up…</strong> It sleeps after inactivity (Render
      free tier) and takes about 30–60 seconds to start. This page checks again automatically.
    </div>
  );
}
