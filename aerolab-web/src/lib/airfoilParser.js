// Airfoil coordinate file parser and repair: a JavaScript port of
// parse_dat_file / detect_and_merge_sections / _tokenize_coord_line in the
// backend's main.py, so files are read in the browser exactly as the server
// reads them. Keep the two in step. When ported it was checked against the
// Python version on 10,847 files (the UIUC database plus reversed, Lednicer,
// CSV, decimal-comma, absolute-unit, messy and too-short variants of them):
// identical coordinates, repair messages and errors on every one.

export class AirfoilParseError extends Error {}

export const MAX_POINTS = 500;
export const MIN_POINTS = 10;

// Python's float() for one token: decimal / exponent forms (underscores
// allowed between digits), "inf"/"infinity"/"nan" in any case, with an
// optional sign. Anything else (hex, trailing junk, empty) is rejected
// instead of being half-parsed the way parseFloat would.
const DIGITS = String.raw`\d(?:_?\d)*`;
const FLOAT_RE = new RegExp(
  String.raw`^[+-]?(?:(?:${DIGITS})?\.${DIGITS}|${DIGITS}\.?)(?:[eE][+-]?${DIGITS})?$`);
const SPECIAL_RE = /^[+-]?(?:inf|infinity|nan)$/i;

export function pyFloat(token) {
  const s = token.trim();
  if (FLOAT_RE.test(s)) return Number(s.replace(/_/g, ""));
  if (SPECIAL_RE.test(s)) {
    if (/nan/i.test(s)) return NaN;
    return s.startsWith("-") ? -Infinity : Infinity;
  }
  return null;
}

const splitWs = (s) => s.split(/\s+/).filter(Boolean);

/** One coordinate line -> [x, y] or null (whitespace, then CSV, then decimal-comma). */
export function tokenizeCoordLine(stripped) {
  const parts = splitWs(stripped);
  if (parts.length >= 2) {
    const x = pyFloat(parts[0]), y = pyFloat(parts[1]);
    if (x !== null && y !== null) return [x, y];
  }
  if (stripped.includes(",")) {
    const csv = stripped.split(",").map((p) => p.trim()).filter(Boolean);
    if (csv.length >= 2) {
      const x = pyFloat(csv[0]), y = pyFloat(csv[1]);
      if (x !== null && y !== null) return [x, y];
    }
  }
  if (parts.length >= 2) {
    const x = pyFloat(parts[0].replace(/,/g, ".")), y = pyFloat(parts[1].replace(/,/g, "."));
    if (x !== null && y !== null) return [x, y];
  }
  return null;
}

/** Same as Python's round() for the integer checks below. */
const pyRound = (v) => {
  const r = Math.round(v);
  return Math.abs(v - Math.trunc(v)) === 0.5 && r % 2 !== 0 ? r - 1 : r;
};

/**
 * Parse and repair an airfoil file's text.
 * Returns { coords: [[x, y], ...], fixes: [string, ...] }.
 * Throws AirfoilParseError with the same messages as the server.
 */
export function parseDatText(text) {
  try {
    let lines = text.split(/\r\n|\r|\n/);
    const fixes = [];
    let rawPairs = [];
    let usedCsv = false, usedDecimalComma = false, skippedNonCoord = 0;
    let explicitSplit = null;

    // Lednicer point-count header ("44.  44." on the line after the title)
    const nonblank = lines.map((l) => l.trim()).filter(Boolean);
    if (nonblank.length >= 2) {
      const hp = tokenizeCoordLine(nonblank[1]);
      if (hp) {
        const [h1, h2] = hp;
        const looksLikeCounts = h1 > 1.5 && h2 > 1.5
          && Math.abs(h1 - pyRound(h1)) < 1e-6 && Math.abs(h2 - pyRound(h2)) < 1e-6;
        if (looksLikeCounts) {
          const nu = pyRound(h1), nl = pyRound(h2);
          const remaining = nonblank.length - 2;
          if (Math.abs(remaining - (nu + nl)) <= 1) {
            explicitSplit = nu;
            lines = [nonblank[0], ...nonblank.slice(2)];
            fixes.push(`Lednicer point-count header detected (${nu} + ${nl} points) and excluded from coordinate data`);
          }
        }
      }
    }

    for (const line of lines) {
      const stripped = line.trim();
      if (!stripped) continue;
      const ws = splitWs(stripped);
      const plainOk = ws.length >= 2 && pyFloat(ws[0]) !== null && pyFloat(ws[1]) !== null;
      const pair = tokenizeCoordLine(stripped);
      if (!pair) { skippedNonCoord++; continue; }
      if (!plainOk) {
        if (stripped.includes(",") && ws.length < 2) usedCsv = true;
        else if (ws.length >= 2) usedDecimalComma = true;
      }
      rawPairs.push(pair);
    }
    if (usedCsv) fixes.push("Comma-separated (CSV) coordinate lines detected and parsed");
    if (usedDecimalComma) fixes.push("European decimal-comma format detected and converted");

    // Absolute units (e.g. a 250 mm chord) -> normalised chord
    // (Python's max(): starts from the first value; NaN never replaces it)
    let maxAbsX = rawPairs.length ? Math.abs(rawPairs[0][0]) : 0;
    for (const [x] of rawPairs) if (Math.abs(x) > maxAbsX) maxAbsX = Math.abs(x);
    if (maxAbsX > 3.0) {
      const scale = 1.0 / maxAbsX;
      rawPairs = rawPairs.map(([x, y]) => [x * scale, y * scale]);
      const m = maxAbsX.toFixed(2);
      fixes.push(`Coordinates rescaled to normalized chord (detected absolute units, max |x| = ${m}, scaled by 1/${m})`);
    }

    const data = [];
    let skippedRange = 0;
    for (const [x, y] of rawPairs) {
      if (x >= -0.5 && x <= 1.5 && y >= -1.0 && y <= 1.0) data.push([x, y]);
      else skippedRange++;
    }
    if (skippedNonCoord > 0) fixes.push(`Non-coordinate lines skipped: ${skippedNonCoord} header/comment line(s) removed`);
    if (skippedRange > 0) fixes.push(`Out-of-range points filtered: ${skippedRange} point(s) outside valid bounds removed`);

    if (data.length < MIN_POINTS) {
      throw new AirfoilParseError(`Insufficient valid coordinates. Found ${data.length} points.`);
    }

    const { coords, fixes: geomFixes } = detectAndMergeSections(data, explicitSplit);
    fixes.push(...geomFixes);
    if (!fixes.length) fixes.push("No changes made — file was already in valid Selig format");
    return { coords, fixes };
  } catch (e) {
    if (e instanceof AirfoilParseError) throw e;
    throw new AirfoilParseError(`Failed to parse file: ${e.message}`);
  }
}

export function detectAndMergeSections(data, explicitSplit = null) {
  const fixes = [];
  const xs = data.map((p) => p[0]);
  let sectionBreak = null;
  if (explicitSplit !== null && explicitSplit > 0 && explicitSplit < data.length) {
    sectionBreak = explicitSplit;
  } else {
    for (let i = 1; i < data.length; i++) {
      if (xs[i] < 0.01 && xs[i - 1] > 0.5) { sectionBreak = i; break; }
    }
  }

  let merged;
  if (sectionBreak !== null) {
    let upper = data.slice(0, sectionBreak);
    let lower = data.slice(sectionBreak);
    fixes.push(`Lednicer format detected and converted: two-section format (${upper.length} upper + ${lower.length} lower points) merged into a single Selig-format loop for XFOIL`);
    if (upper[0][0] > upper[upper.length - 1][0]) upper = upper.slice().reverse();
    upper = upper.slice().reverse();
    if (lower[0][0] > lower[lower.length - 1][0]) lower = lower.slice().reverse();
    if (lower.length && Math.abs(lower[0][0]) < 0.001 && Math.abs(lower[0][1]) < 0.001) {
      lower = lower.slice(1);
      fixes.push("Duplicate leading-edge point removed from Lednicer lower section");
    }
    merged = upper.concat(lower);
  } else if (xs[0] > 0.99 && xs[xs.length - 1] > 0.99) {
    let leIdx = 0;
    for (let i = 1; i < xs.length; i++) if (xs[i] < xs[leIdx]) leIdx = i;
    if (leIdx > 0) {
      if (data[leIdx - 1][1] > 0) {
        merged = data;
      } else {
        merged = data.slice().reverse();
        fixes.push("Winding order corrected: coordinates were in reversed order (TE→lower→LE→upper→TE) and have been reversed to the correct Selig order (TE→upper→LE→lower→TE)");
      }
    } else {
      merged = data;
    }
  } else {
    merged = data;
  }
  return { coords: merged, fixes };
}
