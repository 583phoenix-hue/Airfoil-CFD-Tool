import { useState } from "react";
import { FileDrop, SelectField } from "./ui.jsx";
import { EXAMPLE_AIRFOILS, loadExample, readFileText } from "../lib/files.js";

const MAX_BYTES = 1024 * 1024;

/**
 * Pick a bundled example or upload a .dat/.txt.
 * value: { name, content } | null
 * defaultLabel: when set, adds a first option meaning "no file" (e.g. "NACA 0012 (default)").
 */
export default function AirfoilPicker({ value, onChange, label = "Airfoil", defaultLabel, idPrefix = "" }) {
  const [choice, setChoice] = useState(defaultLabel ? "default" : "upload");
  const [err, setErr] = useState(null);

  const options = [
    ...(defaultLabel ? [["default", defaultLabel]] : []),
    ["upload", "— Upload my own —"],
    // When the default is NACA 0012, its example would just duplicate it
    ...EXAMPLE_AIRFOILS.filter(([, f]) => !(defaultLabel && f === "naca0012.dat")).map(([n, f]) => [f, `Example: ${n}`]),
  ];

  const onChoice = async (c) => {
    setChoice(c);
    setErr(null);
    if (c === "default" || c === "upload") { onChange(null); return; }
    try {
      onChange({ name: c, content: await loadExample(c), example: true });
    } catch (e) {
      setErr(e.message);
      onChange(null);
    }
  };

  const onFiles = async (files) => {
    setErr(null);
    if (!files.length) { onChange(null); return; }
    const f = files[0];
    if (f.size > MAX_BYTES) { setErr("File too large (max 1 MB)."); return; }
    if (!/\.(dat|txt)$/i.test(f.name)) { setErr("Only .dat or .txt files are accepted."); return; }
    try {
      onChange({ name: f.name, content: await readFileText(f) });
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="stack" style={{ gap: 8 }}>
      <SelectField label={label} value={choice} onChange={onChoice} options={options} key={idPrefix} />
      {choice === "upload" && (
        <FileDrop files={value && !value.example ? [value] : []} onFiles={onFiles}
          label="Drop an airfoil .dat here" />
      )}
      {value?.example && <div className="caption">📄 Using example: <strong>{value.name}</strong></div>}
      {err && <div className="alert alert-error">{err}</div>}
    </div>
  );
}
