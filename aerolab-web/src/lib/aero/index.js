// In-browser versions of the backend's /aeroelasticity/* endpoints: same
// inputs, validation, messages and response JSON as main.py, with the
// solvers (divergence.js, reversal.js, flutter.js) running here and XFOIL
// running as WebAssembly.

import { AirfoilParseError, parseDatText } from "../airfoilParser.js";
import { LIMITS } from "../xfoil/analysis.js";
import { XfoilPolarError, analyzeDivergence } from "./divergence.js";
import { analyzeReversal } from "./reversal.js";
import { analyzeFlutter } from "./flutter.js";

export class AeroError extends Error {
  constructor(message, status = 500) { super(message); this.status = status; }
}

const fmtInt = (n) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const MAX_FILE_SIZE = 1024 * 1024;

/** main.py _json_safe: NaN/inf -> null, recursively. */
export function jsonSafe(o) {
  if (Array.isArray(o)) return o.map(jsonSafe);
  if (o && typeof o === "object") {
    const out = {};
    for (const [k, v] of Object.entries(o)) out[k] = jsonSafe(v);
    return out;
  }
  if (typeof o === "number" && !Number.isFinite(o)) return null;
  return o;
}

/** FastAPI's bool form parsing. */
function formBool(v, dflt) {
  if (v === undefined || v === null || v === "") return dflt;
  if (typeof v === "boolean") return v;
  const s = String(v).trim().toLowerCase();
  if (["true", "1", "yes", "on", "t", "y"].includes(s)) return true;
  if (["false", "0", "no", "off", "f", "n"].includes(s)) return false;
  throw new AeroError("Input should be a valid boolean", 422);
}

function num(fields, key, dflt) {
  const v = fields[key];
  if (v === undefined || v === null || v === "") return dflt;
  const n = Number(v);
  if (!Number.isFinite(n)) throw new AeroError(`Input should be a valid number (${key})`, 422);
  return n;
}

function validateCommon(reynolds, vStart, vStep, vMax, rho) {
  if (!(reynolds >= LIMITS.minRe && reynolds <= LIMITS.maxRe)) {
    throw new AeroError(`Reynolds must be ${fmtInt(LIMITS.minRe)} to ${fmtInt(LIMITS.maxRe)}`, 400);
  }
  if (vStart <= 0 || vStep <= 0 || vMax <= vStart) {
    throw new AeroError("Speed sweep needs 0 < 'from' < 'up to' and a positive step", 400);
  }
  if ((vMax - vStart) / vStep > 5000) throw new AeroError("Speed step too small for this range (max 5000 points)", 400);
  if (rho <= 0) throw new AeroError("Air density must be positive", 400);
}

/** Uploaded airfoil -> the repaired file XFOIL loads (main.py _prepare_aero_workdir). */
function prepareSeed(file) {
  if (!file) return null;
  const text = file.content;
  if (new Blob([text]).size > MAX_FILE_SIZE) throw new AeroError("File too large", 400);
  let coords;
  try {
    ({ coords } = parseDatText(text));
  } catch (e) {
    throw new AeroError(e.message, e instanceof AirfoilParseError ? 400 : 500);
  }
  const name = "airfoil_fixed.dat";
  return { name, text: "AIRFOIL\n" + coords.map(([x, y]) => `  ${x.toFixed(6)}  ${y.toFixed(6)}\n`).join("") };
}

/**
 * module: "divergence" | "reversal" | "flutter"
 * fields: the same form fields the page sends to the server
 * file: null or { name, content }
 * runXfoil: XFOIL session runner (xfoilClient.runXfoilSession in the browser)
 */
export async function runAeroLocal(module, fields, file, runXfoil) {
  const reynolds = num(fields, "reynolds", 500000);
  const ncrit = num(fields, "ncrit", 9.0);
  const rho = num(fields, "rho", 1.225);
  let result;
  try {
    if (module === "divergence" || module === "reversal") {
      const isRev = module === "reversal";
      const alphaRoot = num(fields, "alpha_root", 2.0), kAlpha = num(fields, "k_alpha", 2000.0);
      const xEa = num(fields, "x_ea_over_c", 0.35), chord = num(fields, "chord", 1.0), span = num(fields, "span", 1.0);
      const vStart = num(fields, "v_start", isRev ? 2.0 : 5.0), vStep = num(fields, "v_step", 5.0), vMax = num(fields, "v_max", 100.0);
      validateCommon(reynolds, vStart, vStep, vMax, rho);
      if (kAlpha <= 0 || chord <= 0 || span <= 0) throw new AeroError("Stiffness, chord and span must be positive", 400);
      if (!(xEa >= 0.0 && xEa <= 1.0)) throw new AeroError("Elastic axis must be between 0 and 100% chord", 400);
      if (isRev) {
        const flapFrac = num(fields, "flap_chord_fraction", 0.25);
        const flapSource = fields.flap_source ?? "xfoil";
        if (!(flapFrac >= 0.05 && flapFrac <= 0.6)) throw new AeroError("Flap chord fraction must be 0.05 to 0.6", 400);
        if (flapSource !== "xfoil" && flapSource !== "thin_airfoil") {
          throw new AeroError("flap_source must be 'xfoil' or 'thin_airfoil'", 400);
        }
        const seed = prepareSeed(file);
        result = await analyzeReversal(runXfoil, seed, reynolds, ncrit, alphaRoot, kAlpha, xEa, chord, span, rho,
          flapFrac, vStart, vStep, vMax, flapSource);
      } else {
        const seed = prepareSeed(file);
        result = await analyzeDivergence(runXfoil, seed, reynolds, ncrit, alphaRoot, kAlpha, xEa, chord, span, rho,
          vStart, vStep, vMax);
      }
    } else if (module === "flutter") {
      const alphaRef = num(fields, "alpha_ref", 2.0);
      const m = num(fields, "m", 38.49), mu = num(fields, "mu", 8.082);
      const xcgP = num(fields, "xCG_percent", 55.0), xeaP = num(fields, "xEA_percent", 45.0);
      const kh = num(fields, "kh", 9.621), ktheta = num(fields, "ktheta", 9.621), chord = num(fields, "chord", 2.0);
      const useReal = formBool(fields.use_real_airfoil_data, true);
      const vStart = num(fields, "v_start", 0.1), vStep = num(fields, "v_step", 0.5), vMax = num(fields, "v_max", 100.0);
      validateCommon(reynolds, vStart, vStep, vMax, rho);
      if (Math.min(m, mu, kh, ktheta, chord) <= 0) throw new AeroError("Mass, inertia, stiffnesses and chord must be positive", 400);
      if (!(xcgP >= 0 && xcgP <= 100 && xeaP >= 0 && xeaP <= 100)) {
        throw new AeroError("CG and elastic axis must be between 0 and 100% chord", 400);
      }
      const b = chord / 2.0;
      const xCG = (xcgP / 100.0 - 0.5) * chord;
      const xEA = (xeaP / 100.0 - 0.5) * chord;
      const seed = prepareSeed(file);
      result = await analyzeFlutter(runXfoil, seed, reynolds, ncrit, alphaRef, m, mu, xCG, xEA, kh, ktheta, b, rho,
        useReal, vStart, vStep, vMax);
      delete result.history; // legacy tuple form; "modes" carries it all
    } else {
      throw new AeroError("Unknown module", 404);
    }
  } catch (e) {
    if (e instanceof AeroError) throw e;
    if (e instanceof XfoilPolarError) throw new AeroError(e.message, 422);
    throw e; // infrastructure problems (XFOIL unavailable etc.) are handled by the caller
  }
  result.success = true;
  return jsonSafe(result);
}
