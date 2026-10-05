// Single-point airfoil analysis, run with XFOIL compiled to WebAssembly.
// A port of the backend's /upload_airfoil/ path (main.py: upload_airfoil,
// run_xfoil_sync, _run_xfoil_mode and the output parsers) so the browser
// returns the same response shape the server did.
//
// `runXfoil(script, files, timeoutMs)` is injected: it runs one XFOIL
// session and resolves to { stdout, files: { name: text | null } } for the
// output files below, or rejects with an XfoilTimeout. The browser passes a
// Web Worker pool (xfoilClient.js); tests can pass a Node runner.

import { AirfoilParseError, MAX_POINTS, parseDatText } from "../airfoilParser.js";

export const LIMITS = {
  minRe: 1e4, maxRe: 1e7, minAlpha: -10, maxAlpha: 20, minNcrit: 0.1, maxNcrit: 20.0, maxMach: 0.75,
};

export class AnalysisError extends Error {
  constructor(message, status = 500) { super(message); this.status = status; }
}
export class XfoilTimeout extends Error {}

const COORDS = "airfoil.dat";
const CP = "cp_output.txt";
const BL = "bl_output.txt";
const POLAR = "polar_output.txt";

/** Python's str() of a float, so scripts read exactly as the server's did. */
export function pyStr(v) {
  if (Number.isInteger(v) && Math.abs(v) < 1e16) return v.toFixed(1);
  const s = String(v);
  return s.replace(/e([+-])(\d)$/, "e$10$2"); // 1e-7 -> 1e-07
}

const fmtNum = (n, fmt) => (Number.isFinite(n) ? n.toLocaleString("en-US", fmt) : String(n));

export function validateParams({ reynolds, alpha, ncrit = 9.0, mode = "viscous", mach = 0.0 }) {
  const L = LIMITS;
  if (!(reynolds >= L.minRe && reynolds <= L.maxRe)) {
    throw new AnalysisError(`Reynolds must be ${fmtNum(L.minRe)} to ${fmtNum(L.maxRe)}`, 400);
  }
  if (!(alpha >= L.minAlpha && alpha <= L.maxAlpha)) {
    throw new AnalysisError(`Alpha must be ${L.minAlpha} to ${L.maxAlpha} degrees`, 400);
  }
  if (!(ncrit >= L.minNcrit && ncrit <= L.maxNcrit)) {
    throw new AnalysisError(`NCrit must be ${L.minNcrit} to ${pyStr(L.maxNcrit)}`, 400);
  }
  if (!(mach >= 0 && mach <= L.maxMach)) {
    throw new AnalysisError(`Mach must be 0.0 to ${L.maxMach} (XFOIL's compressibility correction is not reliable beyond this)`, 400);
  }
  const m = String(mode).trim().toLowerCase();
  if (m !== "viscous" && m !== "inviscid") {
    throw new AnalysisError("Mode must be one of ['inviscid', 'viscous']", 400);
  }
  return m;
}

/**
 * Warm-start angles for the "ramp" strategy: 0° towards the target in steps of
 * at most 2.5° (the target itself excluded). XFOIL converges much more reliably
 * when each solution starts from the previous angle's; e.g. Clark Y at
 * Re 500k, 5° fails from a cold start in XFOIL 6.996 but converges via 0, 2.5.
 * Returns null when there's nothing to ramp through.
 */
export function rampAngles(alpha) {
  const n = Math.ceil(Math.abs(alpha) / 2.5);
  if (n < 1 || Math.abs(alpha) < 1) return null;
  const out = [];
  for (let i = 0; i < n; i++) out.push(Math.round((alpha * i / n) * 1000) / 1000);
  return out;
}

export function buildScript({ reynolds, alpha, ncrit, mach, viscous, smooth, ramp = null }) {
  const s = ["PLOP", "G", "", `LOAD ${COORDS}`, "PANE"];
  if (smooth) s.push("GDES", "SMOO", "");
  s.push("OPER");
  if (mach && mach > 0) s.push(`MACH ${pyStr(mach)}`);
  if (viscous) s.push(`VISC ${Math.trunc(reynolds)}`, "ITER 500", "VPAR", `N ${pyStr(ncrit)}`, "");
  if (viscous && ramp) for (const a of ramp) s.push(`ALFA ${pyStr(a)}`); // not accumulated
  s.push("PACC", POLAR, "", `ALFA ${pyStr(alpha)}`, `CPWR ${CP}`);
  if (viscous) s.push(`DUMP ${BL}`);
  s.push("PACC", "", "QUIT");
  return s.join("\n");
}

// ── Output parsers (main.py equivalents) ─────────────────────────────────
const isPyFloat = (t) => /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(t) || /^[+-]?(?:inf|infinity|nan)$/i.test(t);
const num = (t) => (/^[+-]?inf/i.test(t) ? (t.startsWith("-") ? -Infinity : Infinity) : /nan/i.test(t) ? NaN : Number(t));
const words = (line) => line.trim().split(/\s+/).filter(Boolean);

export function extractCoefficients(stdout) {
  const out = {};
  const pats = {
    CL: /CL\s*=\s*([-+]?\d*\.?\d+)/g,
    CD: /CD\s*=\s*([-+]?\d*\.?\d+)/g,
    CDp: /CDp\s*=\s*([-+]?\d*\.?\d+)/g,
    Cm: /Cm\s*=\s*([-+]?\d*\.?\d+)/g,
  };
  for (const [k, re] of Object.entries(pats)) {
    const all = [...stdout.matchAll(re)];
    if (all.length) out[k] = Number(all[all.length - 1][1]);
  }
  return out;
}

export function parsePolarRows(text) {
  if (text == null) return [];
  const rows = [];
  let header = false;
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim();
    if (t.startsWith("---")) { header = true; continue; }
    if (!header || !t) continue;
    const p = words(t);
    if (p.every(isPyFloat) && p.length >= 5) rows.push(p.map(num));
  }
  return rows;
}

export function parsePolar(text) {
  if (text == null) return null;
  const rows = [];
  let header = false;
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim();
    if (t.startsWith("---")) { header = true; continue; }
    if (!header || !t) continue;
    const p = words(t);
    if (!p.every(isPyFloat)) continue;
    if (p.length >= 5) rows.push(p.map(num));
  }
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  return { CL: last[1], CD: last[2], CDp: last[3], Cm: last[4] };
}

export function parseCp(text) {
  const x = [], cp = [];
  for (const line of (text || "").split(/\r?\n/)) {
    const t = line.trim();
    if (!t || /\p{L}/u.test(t)) continue;
    const p = words(t);
    if (p.length >= 2 && isPyFloat(p[0]) && isPyFloat(p[p.length - 1])) {
      x.push(num(p[0])); cp.push(num(p[p.length - 1])); // Cp is the last column
    }
  }
  return { x, cp };
}

export function parseBlDump(text) {
  if (text == null) return null;
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    const p = words(line);
    if (p.length < 7) continue;
    if (!p.slice(0, 7).every(isPyFloat)) continue;
    const v = p.slice(0, 7).map(num);
    let H = null;
    if (p.length >= 8) {
      if (!isPyFloat(p[7])) return null; // Python: float() raised -> whole parse returned None
      H = num(p[7]);
    }
    rows.push({ x: v[1], y: v[2], dstar: v[4], theta: v[5], cf: v[6], H });
  }
  if (!rows.length) return null;
  let le = 0;
  for (let i = 1; i < rows.length; i++) if (rows[i].x < rows[le].x) le = i;
  const upper = rows.slice(0, le + 1);
  const lower = [];
  for (const r of rows.slice(le + 1)) {
    if (r.x <= 1.0 + 1e-6) lower.push(r); else break; // wake starts here
  }
  const transition = (rs) => {
    if (rs.length < 4) return null;
    for (let i = 1; i < rs.length - 1; i++) {
      const a = Math.abs(rs[i - 1].cf), b = Math.abs(rs[i].cf);
      if (a > 1e-6 && b > 1e-6 && b / a > 2.5) return rs[i].x;
    }
    return null;
  };
  return { upper, lower, transition_upper_x: transition(upper), transition_lower_x: transition(lower) };
}

// ── One XFOIL mode (main.py _run_xfoil_mode) ─────────────────────────────
async function runMode(runXfoil, datText, p, viscous, smooth, timeoutMs, ramp = null) {
  const script = buildScript({ ...p, viscous, smooth, ramp });
  const { stdout, files } = await runXfoil(script, { [COORDS]: datText }, [CP, BL, POLAR], timeoutMs);
  const mode = viscous ? "VISCOUS" : "INVISCID";
  if (ramp) {
    // The warm-up angles may print failures of their own; what counts is
    // whether the target angle converged, i.e. made it into the polar file
    // (XFOIL only accumulates converged points).
    const ok = parsePolarRows(files[POLAR]).some((r) => Math.abs(r[0] - p.alpha) < 1e-3);
    if (!ok) throw new Error(`Viscous convergence failed at alpha=${pyStr(p.alpha)}`);
  } else {
    const low = stdout.toLowerCase();
    if (stdout.includes("VISCAL:  Convergence failed") || low.includes("not converged") || low.includes("unconverged")) {
      throw new Error(`Viscous convergence failed at alpha=${pyStr(p.alpha)}`);
    }
  }
  if (files[CP] == null) throw new Error(`${mode} did not generate CP output file`);

  let coefficients = extractCoefficients(stdout);
  if (!("CL" in coefficients) && !viscous) {
    const pc = parsePolar(files[POLAR]);
    if (pc && "CL" in pc) coefficients = pc;
  }
  if (!("CL" in coefficients)) throw new Error(`No valid aerodynamic coefficients found for alpha=${pyStr(p.alpha)}`);

  const { x, cp } = parseCp(files[CP]);
  if (!x.length) throw new Error("No pressure data");
  const bl = viscous ? parseBlDump(files[BL]) : null;

  coefficients.mode = viscous ? "viscous" : "inviscid";
  if (viscous) coefficients.ncrit = p.ncrit;
  else coefficients.warning = "INVISCID MODE - CD is unrealistically low";
  return { cp_x: x, cp_values: cp, coefficients, bl_data: bl };
}

const fmt6 = (v) => v.toFixed(6);

/**
 * Analyse one airfoil file at one condition.
 * Resolves to the same object the server's /upload_airfoil/ returned.
 */
export async function analyzeAirfoil(runXfoil, fileText, params) {
  const mode = validateParams(params);
  const p = { reynolds: params.reynolds, alpha: params.alpha, ncrit: params.ncrit ?? 9.0, mach: params.mach ?? 0.0 };

  let coords, fixes;
  try {
    ({ coords, fixes } = parseDatText(fileText));
  } catch (e) {
    throw new AnalysisError(e.message, e instanceof AirfoilParseError ? 400 : 500);
  }
  if (coords.length > MAX_POINTS) throw new AnalysisError(`Too many points (max ${MAX_POINTS})`, 400);

  const datText = "AIRFOIL\n" + coords.map(([x, y]) => `  ${fmt6(x)}  ${fmt6(y)}\n`).join("");

  const attempt = (viscous, smooth, timeoutMs, ramp = null) => runMode(runXfoil, datText, p, viscous, smooth, timeoutMs, ramp);
  let r;
  if (mode === "inviscid") {
    try { r = await attempt(false, false, 20000); } catch (e) { throw new AnalysisError(e.message); }
  } else {
    // 1: viscous, warm-started from 0° (when the angle is 1° or more);
    // 2: viscous from a cold start; 3: viscous, smoothed geometry;
    // 4: inviscid fallback
    const ramp = rampAngles(p.alpha);
    if (ramp) { try { r = await attempt(true, false, 90000, ramp); } catch { /* next strategy */ } }
    if (!r) { try { r = await attempt(true, false, 90000); } catch { /* next strategy */ } }
    if (!r) { try { r = await attempt(true, true, 90000); } catch { /* next strategy */ } }
    if (!r) {
      try { r = await attempt(false, false, 20000); } catch (e) {
        throw new AnalysisError(`All strategies failed. Last error: ${e.message}`);
      }
    }
  }

  return {
    success: true,
    coords_before: coords,
    coords_after: coords,
    num_points: coords.length,
    cp_x: r.cp_x,
    cp_values: r.cp_values,
    coefficients: r.coefficients,
    bl_data: r.bl_data,
    parser_fixes: fixes,
  };
}
