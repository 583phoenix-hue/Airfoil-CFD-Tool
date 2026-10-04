import { useEffect, useId, useRef, useState } from "react";

export function Label({ children, htmlFor, help }) {
  return (
    <label className="field-label" htmlFor={htmlFor}>
      {children}
      {help && <InfoTip text={help} />}
    </label>
  );
}

/** Small (i) with a hover/focus tooltip. */
export function InfoTip({ text }) {
  return (
    <span className="infotip" tabIndex={0} aria-label={text}>
      <span aria-hidden="true">i</span>
      <span className="infotip-body" role="tooltip">{text}</span>
    </span>
  );
}

/**
 * Number input that lets the user type freely (including an empty box or
 * "-") and only reports finite values; clamps on blur.
 */
export function NumberField({ label, help, value, onChange, min, max, step = "any", suffix, disabled }) {
  const id = useId();
  const [text, setText] = useState(String(value));
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(String(value)); }, [value]);
  const commit = () => {
    let v = parseFloat(text);
    if (!Number.isFinite(v)) v = value;
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    setText(String(v));
    onChange(v);
  };
  return (
    <div className="field">
      {label && <Label htmlFor={id} help={help}>{label}</Label>}
      <div className="input-wrap">
        <input id={id} className="input" type="number" inputMode="decimal" value={text} step={step}
          min={min} max={max} disabled={disabled}
          onFocus={() => { focused.current = true; }}
          onChange={(e) => {
            setText(e.target.value);
            const v = parseFloat(e.target.value);
            if (Number.isFinite(v) && (min === undefined || v >= min) && (max === undefined || v <= max)) onChange(v);
          }}
          onBlur={() => { focused.current = false; commit(); }} />
        {suffix && <span className="input-suffix">{suffix}</span>}
      </div>
    </div>
  );
}

export function SliderField({ label, help, value, onChange, min, max, step, format = (v) => v, disabled }) {
  const id = useId();
  return (
    <div className="field">
      <div className="slider-head">
        {label && <Label htmlFor={id} help={help}>{label}</Label>}
        <span className="slider-value mono">{format(value)}</span>
      </div>
      <input id={id} className="slider" type="range" min={min} max={max} step={step} value={value}
        disabled={disabled} onChange={(e) => onChange(parseFloat(e.target.value))} />
    </div>
  );
}

/**
 * Two-thumb range slider. One track, two thumbs: pressing anywhere on the
 * track grabs the nearer thumb, dragging snaps to `step`, the thumbs can't
 * cross, and each thumb works with the arrow keys.
 */
export function RangeField({ label, help, value: [lo, hi], onChange, min, max, step, format = (v) => v }) {
  const id = useId();
  const track = useRef(null);
  const active = useRef(null);
  const span = max - min;
  const snap = (v) => Math.min(max, Math.max(min, Math.round((v - min) / step) * step + min));
  const pct = (v) => ((v - min) / span) * 100;
  const valueAt = (clientX) => {
    const r = track.current.getBoundingClientRect();
    return snap(min + ((clientX - r.left) / r.width) * span);
  };
  const set = (which, v) => {
    if (which === 0) onChange([Math.min(v, hi), hi]);
    else onChange([lo, Math.max(v, lo)]);
  };
  const onDown = (e) => {
    e.preventDefault();
    const v = valueAt(e.clientX);
    // nearer thumb; if both sit on the same value, move whichever way the press is
    let which = Math.abs(v - lo) < Math.abs(v - hi) ? 0 : 1;
    if (lo === hi) which = v < lo ? 0 : 1;
    active.current = which;
    track.current.setPointerCapture(e.pointerId);
    set(which, v);
    track.current.querySelectorAll(".rthumb")[which]?.focus();
  };
  const onMove = (e) => { if (active.current !== null) set(active.current, valueAt(e.clientX)); };
  const onUp = () => { active.current = null; };
  const onKey = (which) => (e) => {
    const v = which === 0 ? lo : hi;
    const d = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step, PageDown: -5 * step, PageUp: 5 * step }[e.key];
    if (d !== undefined) { e.preventDefault(); set(which, snap(v + d)); }
    else if (e.key === "Home") { e.preventDefault(); set(which, min); }
    else if (e.key === "End") { e.preventDefault(); set(which, max); }
  };
  return (
    <div className="field">
      <div className="slider-head">
        {label && <Label htmlFor={id} help={help}>{label}</Label>}
        <span className="slider-value mono">{format(lo)} → {format(hi)}</span>
      </div>
      <div className="rtrack" ref={track} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
        <div className="rtrack-bg" />
        <div className="rtrack-fill" style={{ left: `${pct(lo)}%`, width: `${pct(hi) - pct(lo)}%` }} />
        {[lo, hi].map((v, i) => (
          <button key={i} type="button" id={i === 0 ? id : undefined} className="rthumb" role="slider"
            aria-label={i === 0 ? "From" : "To"} aria-valuemin={min} aria-valuemax={max} aria-valuenow={v}
            style={{ left: `${pct(v)}%`, zIndex: active.current === i ? 3 : 2 }} onKeyDown={onKey(i)} />
        ))}
      </div>
    </div>
  );
}

export function SelectField({ label, help, value, onChange, options }) {
  const id = useId();
  return (
    <div className="field">
      {label && <Label htmlFor={id} help={help}>{label}</Label>}
      <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
      </select>
    </div>
  );
}

export function Checkbox({ label, help, checked, onChange, disabled }) {
  return (
    <label className={`check ${disabled ? "is-disabled" : ""}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
      {help && <InfoTip text={help} />}
    </label>
  );
}

/** Segmented control: options = [[value, label], ...] */
export function Segmented({ value, onChange, options, ariaLabel }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={ariaLabel}>
      {options.map(([v, text]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v}
          className={value === v ? "active" : ""} onClick={() => onChange(v)}>{text}</button>
      ))}
    </div>
  );
}

export function Alert({ kind = "info", children }) {
  return <div className={`alert alert-${kind}`}>{children}</div>;
}

export function Metric({ label, value, sub, help, color }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}{help && <InfoTip text={help} />}</div>
      <div className="metric-value mono" style={color ? { color } : undefined}>{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

export function Details({ summary, children, open = false }) {
  return (
    <details className="details" open={open}>
      <summary>{summary}</summary>
      <div className="details-body">{children}</div>
    </details>
  );
}

export function Spinner({ children }) {
  return (
    <div className="spinner-row" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

export function Progress({ value, children }) {
  return (
    <div className="progress-wrap" role="status">
      <div className="progress"><div className="progress-bar" style={{ width: `${Math.round(value * 100)}%` }} /></div>
      {children && <div className="progress-text">{children}</div>}
    </div>
  );
}

/**
 * File picker with drag-and-drop. Calls onFiles(File[]); shows the chosen
 * file name(s). `files` is the current selection (for display/clearing).
 */
export function FileDrop({ accept = ".dat,.txt", multiple = false, files = [], onFiles, label, hint }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const pick = (list) => {
    const arr = Array.from(list || []);
    if (arr.length) onFiles(multiple ? arr : arr.slice(0, 1));
  };
  return (
    <div
      className={`drop ${over ? "over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}
    >
      <input ref={input} type="file" accept={accept} multiple={multiple} hidden
        onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
      <div className="drop-main">
        <span className="drop-icon" aria-hidden="true">📁</span>
        <div>
          <div style={{ color: "var(--text)" }}>{label || (multiple ? "Drop files here" : "Drop a file here")}</div>
          <div className="drop-hint">{hint || `${accept.replaceAll(",", " ")} · max 1 MB`}</div>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => input.current?.click()}>Browse</button>
      </div>
      {files.length > 0 && (
        <div className="drop-files">
          {files.map((f) => <span key={f.name} className="chip">📄 {f.name}</span>)}
          <button type="button" className="link-btn" onClick={() => onFiles([])}>Clear</button>
        </div>
      )}
    </div>
  );
}

/** Click-to-open popover (used for "ℹ️ File format"). Closes on outside click / Escape. */
export function Popover({ trigger, children, width = 560 }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div className="popover-anchor" ref={ref}>
      <button type="button" className="btn btn-secondary btn-sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {trigger}
      </button>
      {open && <div className="popover" style={{ width }} role="dialog">{children}</div>}
    </div>
  );
}

/** The "AeroLab Parser >" terminal box from the Streamlit page. */
export function ParserBox({ filename, fixes }) {
  const clean = !fixes?.length || (fixes.length === 1 && /No changes made/.test(fixes[0]));
  return (
    <div className="parser-box mono">
      <span style={{ color: "var(--c2)", fontWeight: 600 }}>AeroLab Parser</span>
      <span style={{ color: "var(--c3)" }}> &gt;</span>
      <span style={{ color: "var(--text)" }}> {filename}</span>
      <br />
      <span style={{ color: "var(--c5)" }}>{clean ? "✅ File accepted as-is:" : `⚠️  ${fixes.length} repair(s) applied:`}</span>
      <br />
      <span style={{ color: "var(--c3)", whiteSpace: "pre-wrap" }}>
        {clean ? "  ✔  No changes made — file was already in valid Selig format"
          : fixes.map((f) => `  ✔  ${f}`).join("\n")}
      </span>
    </div>
  );
}

export function SectionTitle({ children, right }) {
  return (
    <div className="section-head">
      <h2 className="section-h">{children}</h2>
      {right}
    </div>
  );
}

/**
 * Progress bar for a single long request whose length we can't measure
 * (the server doesn't report progress). It eases towards 95% over
 * `expected` seconds, shows the elapsed time, and the caller unmounts it
 * when the request finishes.
 */
export function TimedProgress({ expected = 60, label, stages = [] }) {
  const [t, setT] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const id = setInterval(() => setT((performance.now() - start) / 1000), 250);
    return () => clearInterval(id);
  }, []);
  // 1 - e^(-3t/T): ~63% at T/3, ~95% at T, then creeps on but never reaches 100
  const value = Math.min(0.97, 1 - Math.exp((-3 * t) / expected));
  const stage = [...stages].reverse().find(([at]) => t >= at)?.[1];
  const secs = Math.floor(t);
  return (
    <Progress value={value}>
      {stage || label} · {secs} s
      {t > expected ? " (taking longer than usual, still working…)" : ` (usually under ${expected} s)`}
    </Progress>
  );
}
