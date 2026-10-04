/*
 * cpParser.js — browser port of pages/cp_target_parser.py (same rules, same
 * messages), so a Cp file can be read and previewed without a server call.
 *
 * parseCpFile(text) -> { upper, lower, format, notes, warnings, upper_guessed, n_upper, n_lower }
 *   upper/lower: [[x, Cp], ...] sorted by x, x in [0, 1]
 * Throws CpFileError with a user-facing message on failure.
 */

export const MAX_POINTS_PER_SURFACE = 500;
export const MIN_POINTS_PER_SURFACE = 5;

const UPPER_WORDS = ["upper", "top", "suction", "extrados"];
const LOWER_WORDS = ["lower", "bottom", "pressure side", "intrados"];
const CP_NAMES = ["cpv", "cp_v", "cp", "c_p", "pressure_coefficient", "pressurecoefficient", "cpressure",
  "coefpressure", "pressure coefficient", "cpi", "cp_i"];
const X_NAMES = ["x", "x/c", "xc", "x_c", "x/chord", "x (m)", "x(m)", "x [m]", "coordx", "points:0"];
const Y_NAMES = ["y", "y/c", "yc", "y_c", "y/chord", "y (m)", "y(m)", "y [m]", "coordy", "points:1"];

export class CpFileError extends Error {}

const NUM = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][-+]?\d+)?$/;

// Python's g format for the "x ran from A to B" note
const g = (v) => {
  if (v === 0) return "0";
  const s = Number(v.toPrecision(6));
  const a = Math.abs(s);
  if (a >= 1e-4 && a < 1e6) return String(s);
  return s.toExponential().replace(/e([+-])(\d)$/, "e$10$2");
};
const f2 = (v) => v.toFixed(2);

function tokens(line, european) {
  let s = line.trim().replace(/^"+|"+$/g, "").replace(/"/g, "");
  let parts;
  if (european) {
    s = s.replace(/(\d),(\d)/g, "$1.$2");
    parts = s.split(/[;\s\t]+/);
  } else {
    parts = s.split(/[,;\s\t]+/);
  }
  return parts.filter((p) => p !== "");
}

function asNumbers(toks) {
  const out = [];
  for (const t of toks) {
    if (!NUM.test(t)) return null;
    out.push(parseFloat(t.replace(/[dD]/, "e")));
  }
  return out;
}

function detectEuropean(lines) {
  const sample = lines.filter((l) => /\d/.test(l)).slice(0, 200);
  if (!sample.length) return false;
  const hasDot = sample.some((l) => /\d\.\d/.test(l));
  const hasCommaDec = sample.some((l) => /\d,\d/.test(l));
  const usesSemicolon = sample.some((l) => l.includes(";"));
  if (hasCommaDec && !hasDot) {
    return usesSemicolon || sample.every((l) => /^\s*[-+\d,eE\s]+\s*$/.test(l));
  }
  return false;
}

function nameIndex(names, wanted) {
  const low = names.map((n) => n.trim().toLowerCase().replace(/^"+|"+$/g, ""));
  for (const w of wanted) {
    const i = low.indexOf(w);
    if (i >= 0) return i;
  }
  return null;
}

function readBlocks(text) {
  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const european = detectEuropean(lines);
  const blocks = [];
  const labels = [];
  let header = null;
  let cur = [];
  let pendingLabel = "";
  let width = null;

  const close = () => {
    if (cur.length) {
      blocks.push(cur);
      labels.push(pendingLabel);
      pendingLabel = "";
    }
    cur = [];
    width = null;
  };

  for (const line of lines) {
    const s = line.trim();
    if (!s) { close(); continue; }
    if ("#%!".includes(s[0]) || s.startsWith("//")) {
      const txt = s.replace(/^[#%!/ ]+/, "").trim();
      const names = tokens(txt, false);
      if (header === null && names.length && asNumbers(names) === null && nameIndex(names, CP_NAMES) !== null) {
        header = names.map((n) => n.toLowerCase());
      } else {
        close();
        pendingLabel = (pendingLabel + " " + txt).trim();
      }
      continue;
    }
    const toks = tokens(s, european);
    const nums = asNumbers(toks);
    if (nums === null) {
      if (header === null && (nameIndex(toks, CP_NAMES) !== null || nameIndex(toks, X_NAMES) !== null)) {
        header = toks.map((t) => t.toLowerCase());
      } else {
        close();
        pendingLabel = (pendingLabel + " " + s).trim();
      }
      continue;
    }
    if (nums.length < 2) { close(); continue; }
    if (width !== null && nums.length !== width) close();
    width = nums.length;
    cur.push(nums);
  }
  close();
  return { blocks, header, labels, european };
}

const col = (block, i) => block.map((r) => r[i]);
const min = (a) => a.reduce((m, v) => (v < m ? v : m), Infinity);
const max = (a) => a.reduce((m, v) => (v > m ? v : m), -Infinity);
const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
const argmin = (a) => a.reduce((bi, v, i) => (v < a[bi] ? i : bi), 0);

function pickColumns(block, header, notes) {
  const ncol = block[0].length;
  if (header !== null && header.length === ncol) {
    const ix = nameIndex(header, X_NAMES);
    const iy = nameIndex(header, Y_NAMES);
    const ic = nameIndex(header, CP_NAMES);
    if (ix !== null && ic !== null) {
      notes.add(`Used the columns named '${header[ix]}' (x)`
        + (iy !== null ? `, '${header[iy]}' (y)` : "")
        + ` and '${header[ic]}' (Cp).`);
      return [col(block, ix), iy !== null ? col(block, iy) : null, col(block, ic)];
    }
  }
  if (header !== null && nameIndex(header, ["pressure"]) !== null && nameIndex(header, CP_NAMES) === null) {
    throw new CpFileError("The file has a 'Pressure' column but no pressure-coefficient column. "
      + "Export Cp (e.g. 'Pressure_Coefficient' in SU2), not pressure in Pa.");
  }
  if (ncol === 2) return [col(block, 0), null, col(block, 1)];
  if (ncol === 3) {
    const xs = col(block, 0);
    const ys = col(block, 1);
    const span = max(xs) - min(xs);
    if (span > 0 && (max(ys) - min(ys)) / span > 0.45) {
      throw new CpFileError("The file has 3 columns but the middle one doesn't look like airfoil y "
        + "coordinates (it may be a second Cp column, e.g. inviscid and viscous). "
        + "Add a header line naming the columns (e.g. 'x Cpi Cpv') or keep just x and Cp.");
    }
    notes.add("Read three columns as x, y, Cp.");
    return [xs, ys, col(block, 2)];
  }
  if (ncol === 4) {
    throw new CpFileError("The file has 4 numeric columns and no header saying which one is Cp. "
      + "Add a header line such as 'x y Cp' or keep just the x and Cp columns.");
  }
  throw new CpFileError(`The file has ${ncol} numeric columns and no header naming them. Add a header `
    + "line (e.g. 'x, y, Cp') or keep just two columns: x and Cp.");
}

function isLoop(x) {
  const i = argmin(x);
  if (i < 2 || i > x.length - 3) return [false, i];
  const a = x.slice(0, i + 1);
  const b = x.slice(i);
  const frac = (arr, ok) => {
    let n = 0;
    for (let k = 1; k < arr.length; k++) if (ok(arr[k] - arr[k - 1])) n++;
    return n / (arr.length - 1);
  };
  const down = frac(a, (d) => d <= 1e-9);
  const up = frac(b, (d) => d >= -1e-9);
  return [down > 0.9 && up > 0.9, i];
}

function labelSide(label) {
  const l = label.toLowerCase();
  if (UPPER_WORDS.some((w) => l.includes(w))) return "upper";
  if (LOWER_WORDS.some((w) => l.includes(w))) return "lower";
  return null;
}

// numpy.quantile (linear interpolation)
function quantile(sorted, q) {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// numpy.interp (xp increasing, clamps outside)
export function interp(x, xp, fp) {
  if (x <= xp[0]) return fp[0];
  if (x >= xp[xp.length - 1]) return fp[fp.length - 1];
  let lo = 0;
  let hi = xp.length - 1;
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1;
    if (xp[m] <= x) lo = m; else hi = m;
  }
  const t = (x - xp[lo]) / (xp[hi] - xp[lo] || 1);
  return fp[lo] + t * (fp[hi] - fp[lo]);
}

function split(blocks, header, labels, notes) {
  let parsed = blocks.map((b) => pickColumns(b, header, notes));

  if (parsed.length === 2) {
    const sides = [labelSide(labels[0]), labelSide(labels[1])];
    const [[x1, y1, c1], [x2, y2, c2]] = parsed;
    notes.fmt = "two blocks (upper and lower surface)";
    if ((sides[0] === "lower" && sides[1] === "upper") || sides[0] === "lower" || sides[1] === "upper") {
      notes.add("Two blocks found; the labels say the first is the lower surface.");
      return [[x2, c2], [x1, c1], false];
    }
    if (sides[0] === "upper" || sides[1] === "lower") {
      notes.add("Two blocks found; the labels say the first is the upper surface.");
      return [[x1, c1], [x2, c2], false];
    }
    if (y1 !== null && y2 !== null) {
      notes.add("Two blocks found; the one with larger y was taken as the upper surface.");
      return mean(y1) >= mean(y2) ? [[x1, c1], [x2, c2], false] : [[x2, c2], [x1, c1], false];
    }
    notes.add("Two blocks found with no labels; the first was taken as the upper surface.");
    return [[x1, c1], [x2, c2], true];
  }

  if (parsed.length > 2) {
    const bigIdx = parsed.map((p, i) => (p[0].length >= MIN_POINTS_PER_SURFACE ? i : -1)).filter((i) => i >= 0);
    if (bigIdx.length === 2) {
      notes.add("Ignored short blocks with too few points.");
      return split(bigIdx.map((i) => blocks[i]), header, bigIdx.map((i) => labels[i]), notes);
    }
    if (bigIdx.length === 1) {
      parsed = [parsed[bigIdx[0]]];
    } else {
      throw new CpFileError(`Found ${parsed.length} separate blocks of numbers. Use either one `
        + "continuous list or exactly two blocks (upper, then lower).");
    }
  }

  const [x, y, c] = parsed[0];
  const [loop, ile] = isLoop(x);
  if (y !== null) {
    if (loop) {
      const upperFirst = mean(y.slice(0, ile + 1)) >= mean(y.slice(ile));
      notes.add("One continuous loop around the airfoil; y was used to tell the surfaces apart.");
      notes.fmt = "x, y, Cp loop";
      const a = [x.slice(0, ile + 1), c.slice(0, ile + 1)];
      const b = [x.slice(ile), c.slice(ile)];
      return upperFirst ? [a, b, false] : [b, a, false];
    }
    // Not a loop (e.g. SU2 mesh order): split by y relative to a camber line
    // estimated from the data itself.
    const order = x.map((_, i) => i).sort((i, j) => x[i] - x[j]);
    const xs = order.map((i) => x[i]);
    const ys = order.map((i) => y[i]);
    const nb = Math.max(4, Math.min(40, Math.floor(x.length / 6)));
    const edges = Array.from({ length: nb + 1 }, (_, k) => quantile(xs, k / nb));
    const cx = [];
    const cy = [];
    for (let k = 0; k < nb; k++) {
      const a = edges[k];
      const b = edges[k + 1];
      const sel = [];
      for (let i = 0; i < xs.length; i++) if (xs[i] >= a && xs[i] <= b) sel.push(ys[i]);
      if (sel.length >= 2) { cx.push(0.5 * (a + b)); cy.push(0.5 * (max(sel) + min(sel))); }
    }
    const camber = x.map((xi) => (cx.length ? interp(xi, cx, cy) : 0));
    const up = y.map((yi, i) => yi >= camber[i]);
    const lo = y.map((yi, i) => yi < camber[i]);
    const le = argmin(x);
    up[le] = lo[le] = true;
    const nUp = up.filter(Boolean).length;
    const nLo = lo.filter(Boolean).length;
    if (nUp < MIN_POINTS_PER_SURFACE || nLo < MIN_POINTS_PER_SURFACE) {
      throw new CpFileError("Couldn't tell the upper and lower surfaces apart from the y column.");
    }
    notes.add("Surfaces told apart by the sign of y.");
    notes.fmt = "x, y, Cp points";
    const pick = (mask, arr) => arr.filter((_, i) => mask[i]);
    return [[pick(up, x), pick(up, c)], [pick(lo, x), pick(lo, c)], false];
  }

  if (loop) {
    notes.add("One continuous loop around the airfoil (XFOIL order). By convention the first "
      + "half (trailing edge to leading edge) is the upper surface. If the preview looks "
      + "swapped, tick 'Swap upper/lower'.");
    notes.fmt = "x, Cp loop (XFOIL order)";
    return [[x.slice(0, ile + 1), c.slice(0, ile + 1)], [x.slice(ile), c.slice(ile)], true];
  }

  throw new CpFileError(
    "Couldn't tell the upper and lower surfaces apart. The x values don't go around the airfoil "
    + "in one loop, and there is no y column or surface label. Use one of: (1) one loop from the "
    + "trailing edge over the upper surface to the leading edge and back along the lower surface, "
    + "like XFOIL's CPWR output; (2) three columns x, y, Cp; or (3) two blocks separated by a "
    + "blank line, labelled 'upper' and 'lower'.");
}

function normalise(upper, lower, notes) {
  const allx = upper[0].concat(lower[0]);
  const x0 = min(allx);
  const x1 = max(allx);
  const span = x1 - x0;
  if (span <= 0) throw new CpFileError("All x values are the same.");
  if (Math.abs(x0) > 1e-3 || Math.abs(x1 - 1.0) > 1e-3) {
    let unit = "";
    if (span >= 90 && span <= 110) unit = " (looks like percent chord)";
    else if (span > 1.5) unit = " (looks like a length unit, e.g. mm)";
    notes.add(`x ran from ${g(x0)} to ${g(x1)}${unit}; rescaled to 0-1 chord.`);
  }
  const norm = ([sx, sc]) => {
    const idx = sx.map((_, i) => i).sort((i, j) => (sx[i] - x0) - (sx[j] - x0) || i - j);
    // merge exact duplicate x (rounded to 7 places), averaging Cp
    const groups = new Map();
    for (const i of idx) {
      const k = Math.round(((sx[i] - x0) / span) * 1e7) / 1e7;
      const gr = groups.get(k) || { s: 0, n: 0 };
      gr.s += sc[i]; gr.n += 1;
      groups.set(k, gr);
    }
    const ux = [...groups.keys()].sort((a, b) => a - b);
    return [ux, ux.map((k) => groups.get(k).s / groups.get(k).n)];
  };
  return [norm(upper), norm(lower)];
}

// numpy.round rounds halves to even
function roundHalfEven(v) {
  const r = Math.round(v);
  return Math.abs(v - Math.trunc(v)) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

function downsample([x, c], notes, name) {
  if (x.length <= MAX_POINTS_PER_SURFACE) return [x, c];
  const idx = [...new Set(Array.from({ length: MAX_POINTS_PER_SURFACE },
    (_, k) => roundHalfEven((k * (x.length - 1)) / (MAX_POINTS_PER_SURFACE - 1))))];
  notes.add(`The ${name} surface had ${x.length} points; thinned evenly to ${idx.length}.`);
  return [idx.map((i) => x[i]), idx.map((i) => c[i])];
}

function checks(up, lo, warnings) {
  for (const [name, [x]] of [["upper", up], ["lower", lo]]) {
    if (x.length < MIN_POINTS_PER_SURFACE) {
      throw new CpFileError(`The ${name} surface has only ${x.length} points; at least `
        + `${MIN_POINTS_PER_SURFACE} are needed.`);
    }
    if (min(x) > 0.05 || max(x) < 0.95) {
      warnings.push(`The ${name} surface only covers x/c = ${f2(min(x))} to ${f2(max(x))}. `
        + "Outside that range the target is held at the nearest value, so the design "
        + "there is not really controlled.");
    }
    const nLe = x.filter((v) => v < 0.05).length;
    if (nLe < 2) {
      warnings.push(`Only ${nLe} point(s) in the first 5% of chord on the ${name} `
        + "surface. The suction peak there is poorly defined, so lift and the "
        + "leading-edge shape may not match well.");
    }
  }
  const allc = up[1].concat(lo[1]);
  const absMaxI = allc.reduce((bi, v, i) => (Math.abs(v) > Math.abs(allc[bi]) ? i : bi), 0);
  if (Math.abs(allc[absMaxI]) > 20) {
    throw new CpFileError(`Cp values reach ${allc[absMaxI].toFixed(0)}. That looks like pressure `
      + "(e.g. in Pa), not the pressure coefficient Cp. Export Cp instead.");
  }
  const cmax = max(allc);
  const cmin = min(allc);
  const inverted = cmax > 1.2 && cmin >= -1.05;
  if (cmax > 1.05 && !inverted) {
    warnings.push(`Cp reaches ${f2(cmax)}. Cp can't exceed 1 (stagnation) in incompressible `
      + "flow; those points will be capped at 1.");
  }
  if (inverted) {
    warnings.push(`Cp goes up to ${f2(cmax)} but never below ${f2(cmin)}. Real Cp can't exceed `
      + "1, while the suction side usually goes well below -1, so the file probably "
      + "contains -Cp (some tools plot Cp upside down). Check the preview.");
  } else if (cmin > 0.0) {
    warnings.push("Every Cp value is positive. Airfoils always have suction (negative Cp) somewhere, "
      + "so the file may contain -Cp instead of Cp. Check the preview.");
  }
  const teGap = Math.abs(interp(1.0, up[0], up[1]) - interp(1.0, lo[0], lo[1]));
  if (teGap > 0.15) {
    warnings.push(`Upper and lower Cp differ by ${f2(teGap)} at the trailing edge. Real flow `
      + "leaves with equal pressure on both sides; check that the surfaces aren't "
      + "mixed up.");
  }
}

const r6 = (v) => Math.round(v * 1e6) / 1e6;

export function parseCpFile(text) {
  if (typeof text !== "string" || text.includes("\u0000")) {
    throw new CpFileError("The file isn't readable text. Upload a .dat, .txt or .csv file.");
  }
  text = text.replace(/^﻿/, "");
  const items = [];
  const notes = { fmt: "", items, add(s) { if (!items.includes(s)) items.push(s); } };
  const warnings = [];
  const { blocks, header, labels, european } = readBlocks(text);
  if (!blocks.length) {
    throw new CpFileError("No numeric data found. The file needs rows of numbers: x and Cp (or x, y, Cp).");
  }
  if (european) notes.add("Read decimal commas (e.g. 0,25) as decimal points.");
  const [upper, lower, guessed] = split(blocks, header, labels, notes);
  let [up, lo] = normalise(upper, lower, notes);
  up = downsample(up, notes, "upper");
  lo = downsample(lo, notes, "lower");
  checks(up, lo, warnings);
  return {
    upper: up[0].map((x, i) => [r6(x), r6(up[1][i])]),
    lower: lo[0].map((x, i) => [r6(x), r6(lo[1][i])]),
    format: notes.fmt,
    notes: items,
    warnings,
    upper_guessed: !!guessed,
    n_upper: up[0].length,
    n_lower: lo[0].length,
  };
}

/** XFOIL-order loop (x, Cp), which parseCpFile reads back unchanged. */
export function curveToDat(upper, lower, alpha, reynolds) {
  const u = [...upper].sort((a, b) => a[0] - b[0]);
  const l = [...lower].sort((a, b) => a[0] - b[0]);
  let head = "# AeroLab target Cp";
  if (alpha !== undefined && alpha !== null) head += `  alpha=${alpha} deg`;
  if (reynolds !== undefined && reynolds !== null) head += `  Re=${Math.round(reynolds)}`;
  const pad = (s, n) => s.padStart(n);
  const lines = [head, "# Order: trailing edge -> upper surface -> leading edge -> lower surface -> trailing edge",
    "#      x          Cp"];
  for (const [x, c] of [...u].reverse()) lines.push(`  ${pad(x.toFixed(6), 10)} ${pad(c.toFixed(5), 10)}`);
  const lower2 = l.length && u.length && Math.abs(l[0][0] - u[0][0]) < 1e-9 ? l.slice(1) : l;
  for (const [x, c] of lower2) lines.push(`  ${pad(x.toFixed(6), 10)} ${pad(c.toFixed(5), 10)}`);
  return lines.join("\n") + "\n";
}

/** Lift implied by the target curve: integral of (Cp_lower - Cp_upper) dx, times cos(alpha). */
export function curveTargetCl(upper, lower, alphaDeg) {
  const u = [...upper].sort((a, b) => a[0] - b[0]);
  const l = [...lower].sort((a, b) => a[0] - b[0]);
  const ux = u.map((p) => p[0]); const uc = u.map((p) => p[1]);
  const lx = l.map((p) => p[0]); const lc = l.map((p) => p[1]);
  const n = 1001;
  let cn = 0;
  let prev = null;
  for (let i = 0; i < n; i++) {
    const x = i / (n - 1);
    const d = interp(x, lx, lc) - interp(x, ux, uc);
    if (prev !== null) cn += 0.5 * (prev + d) * (1 / (n - 1));
    prev = d;
  }
  return cn * Math.cos((alphaDeg * Math.PI) / 180);
}

/** Uploaded curve -> the editor's 41 cosine-spaced points per surface. */
export function resampleForEditor(upper, lower, n = 41) {
  const x = Array.from({ length: n }, (_, i) => 0.5 * (1 - Math.cos((Math.PI * i) / (n - 1))));
  const ux = upper.map((p) => p[0]); const uc = upper.map((p) => p[1]);
  const lx = lower.map((p) => p[0]); const lc = lower.map((p) => p[1]);
  const cu = x.map((v) => interp(v, ux, uc));
  const cl = x.map((v) => interp(v, lx, lc));
  const le = Math.min(1.0, Math.max(cu[0], cl[0]));
  const te = 0.5 * (cu[n - 1] + cl[n - 1]);
  cu[0] = cl[0] = le;
  cu[n - 1] = cl[n - 1] = te;
  const r4 = (v) => Math.round(v * 1e4) / 1e4;
  return { x: x.map(r4), upper: cu.map(r4), lower: cl.map(r4) };
}
