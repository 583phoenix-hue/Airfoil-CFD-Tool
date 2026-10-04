// Small helpers for reading uploads and producing downloads in the browser.

export function readFileText(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(new Error("Couldn't read the file."));
    r.readAsText(file);
  });
}

export function downloadText(filename, text, mime = "text/plain") {
  downloadBlob(filename, new Blob([text], { type: mime }));
}

export function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** rows: array of objects; columns: optional ordered list of keys */
export function toCsv(rows, columns) {
  if (!rows.length) return "";
  const cols = columns || Object.keys(rows[0]);
  return [cols.join(","), ...rows.map((r) => cols.map((c) => csvCell(r[c])).join(","))].join("\n") + "\n";
}

export const stem = (name) => (name || "airfoil").replace(/\.(dat|txt)$/i, "");

export const EXAMPLE_AIRFOILS = [
  ["NACA 0012", "naca0012.dat"],
  ["NACA 4412", "naca4412.dat"],
  ["Clark Y", "clarky.dat"],
  ["S1223", "s1223.dat"],
  ["Eppler 387", "e387.dat"],
];

export async function loadExample(filename) {
  const res = await fetch(`/examples/${filename}`);
  if (!res.ok) throw new Error(`Example airfoil not found: ${filename}`);
  return res.text();
}
