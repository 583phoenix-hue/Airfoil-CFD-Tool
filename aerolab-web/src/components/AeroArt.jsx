import { useId } from "react";

// Technical schematics for the three aeroelasticity modules, drawn in the
// style of textbook figures: a real NACA 0012 section (computed, not traced),
// dash-dot reference lines, angle arcs, force/moment arrows and labelled
// structural supports. Light line-art on the site's dark background.

const INK = "#dfe6f3";        // outlines, reference lines, labels
const DIM = "#8f9ab3";        // dimensions, leaders, secondary text
const FORCE = "#4fd1ff";      // lift and moments
const FLAP = "#ffa64d";       // control surface
const SPRING = "#9ab0dd";     // structure: posts, springs, ground
const FAIL = "#ff5c5c";       // the instability itself
const BODY = "#161d2e";       // airfoil fill
const SANS = "Inter, system-ui, sans-serif";
const SERIF = "'Times New Roman', Georgia, serif";

const rad = (d) => (d * Math.PI) / 180;

// NACA 00xx half-thickness at chord fraction x
const yt = (x, t = 0.12) => 5 * t * (0.2969 * Math.sqrt(x) - 0.126 * x - 0.3516 * x * x + 0.2843 * x ** 3 - 0.1036 * x ** 4);
const cosx = (a, b, n) => Array.from({ length: n + 1 }, (_, i) => a + (b - a) * 0.5 * (1 - Math.cos((Math.PI * i) / n)));

/** Placement of a section: chord-fraction coordinates -> screen. Pivot at chord fraction xp
 *  sits at (ox, oy); `nose` is the nose-up angle in degrees. */
function placer({ ox, oy, c, xp, nose }) {
  const b = rad(nose), cb = Math.cos(b), sb = Math.sin(b);
  return ([x, y]) => {
    const dx = (x - xp) * c, dy = y * c;
    return [ox + dx * cb + dy * sb, oy - (-dx * sb + dy * cb)];
  };
}
const pathOf = (pts, close = true) => pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("") + (close ? "Z" : "");

function sectionPath(T, x0 = 0, x1 = 1) {
  const xs = cosx(x0, x1, 60);
  const up = xs.map((x) => [x, yt(x)]);
  const lo = xs.map((x) => [x, -yt(x)]).reverse();
  return pathOf([...up, ...lo].map(T));
}

/** Main body up to the hinge (rounded off) plus a deflected flap with a round nose. */
function flappedPaths(T, xh, flapDeg) {
  const gap = 0.012;
  const body = sectionPath(T, 0, xh - gap);
  const r = yt(xh);
  const f = rad(flapDeg), cf = Math.cos(f), sf = Math.sin(f);
  const rot = ([x, y]) => { const dx = x - xh, dy = y; return [xh + dx * cf + dy * sf, -dx * sf + dy * cf]; };
  const xs = cosx(xh, 1, 30);
  const up = xs.map((x) => [x, yt(x)]);
  const lo = xs.map((x) => [x, -yt(x)]).reverse();
  const nose = Array.from({ length: 13 }, (_, i) => { const a = Math.PI / 2 + (Math.PI * i) / 12; return [xh + r * Math.cos(a), r * Math.sin(a)]; });
  // upper surface hinge→TE, lower surface TE→hinge, then the round nose back up
  const flap = pathOf([...up, ...lo, ...nose.reverse()].map(rot).map(T));
  return { body, flap, rot };
}

function arcPath(cx, cy, r, a0, a1) {
  const p = (a) => [cx + r * Math.cos(rad(a)), cy + r * Math.sin(rad(a))];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
  const sweep = a1 > a0 ? 1 : 0;
  return `M${x0.toFixed(1)},${y0.toFixed(1)}A${r},${r} 0 ${large} ${sweep} ${x1.toFixed(1)},${y1.toFixed(1)}`;
}

function Defs({ id }) {
  const head = (key, color) => (
    <marker id={`${id}-${key}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 Z" fill={color} />
    </marker>
  );
  return (
    <defs>
      {head("ink", INK)}{head("dim", DIM)}{head("force", FORCE)}{head("flap", FLAP)}{head("spring", SPRING)}{head("fail", FAIL)}
      <marker id={`${id}-mom`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4.5" markerHeight="4.5" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 Z" fill={FORCE} />
      </marker>
      <pattern id={`${id}-hatch`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="7" stroke={SPRING} strokeWidth="1.6" />
      </pattern>
    </defs>
  );
}

function Ground({ id, x, y, w = 56 }) {
  return (
    <g>
      <rect x={x - w / 2} y={y} width={w} height={11} fill={`url(#${id}-hatch)`} opacity="0.75" />
      <line x1={x - w / 2} y1={y} x2={x + w / 2} y2={y} stroke={SPRING} strokeWidth="2.4" />
    </g>
  );
}

function Freestream({ id, x0 = 14, x1 = 88, ys, label = "V" }) {
  const mid = ys[Math.floor(ys.length / 2)];
  return (
    <g>
      {ys.map((y) => <line key={y} x1={x0} y1={y} x2={x1} y2={y} stroke={INK} strokeWidth="2.6" markerEnd={`url(#${id}-ink)`} />)}
      <text x={x0 + 8} y={mid - 8} fill={INK} fontFamily={SERIF} fontStyle="italic" fontSize="20" fontWeight="600">{label}</text>
    </g>
  );
}

function Label({ x, y, children, anchor = "start", size = 14, color = INK, halo = false, serif = false, italic = false, weight }) {
  return (
    <text x={x} y={y} textAnchor={anchor} fill={color} fontFamily={serif ? SERIF : SANS} fontSize={size}
      fontStyle={italic ? "italic" : "normal"} fontWeight={weight}
      {...(halo ? { stroke: "#0a0d14", strokeWidth: 4, paintOrder: "stroke", strokeLinejoin: "round" } : {})}>
      {children}
    </text>
  );
}

function Dimension({ id, x0, x1, y, label }) {
  return (
    <g>
      <line x1={x0} y1={y} x2={x1} y2={y} stroke={DIM} strokeWidth="1.4" markerStart={`url(#${id}-dim)`} markerEnd={`url(#${id}-dim)`} />
      <Label x={(x0 + x1) / 2} y={y - 7} anchor="middle" serif italic size={16} color={INK}>{label}</Label>
    </g>
  );
}

/** Curved moment arrow around (cx, cy). */
function Moment({ id, cx, cy, r = 17, from = 200, to = -40, color = FORCE }) {
  return <path d={arcPath(cx, cy, r, from, to)} fill="none" stroke={color} strokeWidth="2.2" markerEnd={`url(#${id}-mom)`} />;
}

/** Spiral torsion spring centred on (cx, cy), ending at the bottom so a post can attach. */
function TorsionSpring({ cx, cy, r0 = 6, r1 = 19, turns = 2.2 }) {
  const pts = [];
  const n = 90;
  for (let i = 0; i <= n; i++) {
    const t = i / n, a = Math.PI / 2 + t * turns * 2 * Math.PI, r = r0 + (r1 - r0) * t;
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return <path d={pathOf(pts, false)} fill="none" stroke={SPRING} strokeWidth="1.8" />;
}

/** Zig-zag linear spring from (x, y0) to (x, y1). */
function CoilSpring({ x, y0, y1, n = 7, w = 11 }) {
  const lead = 10, pts = [[x, y0], [x, y0 + lead]];
  const L = y1 - y0 - 2 * lead;
  for (let i = 0; i < n * 2; i++) pts.push([x + (i % 2 ? -w : w), y0 + lead + (L * (i + 0.5)) / (n * 2)]);
  pts.push([x, y1 - lead], [x, y1]);
  return <path d={pathOf(pts, false)} fill="none" stroke={SPRING} strokeWidth="1.8" strokeLinejoin="round" />;
}

function Pivot({ x, y }) {
  return (
    <g>
      <circle cx={x} cy={y} r="8" fill="none" stroke={SPRING} strokeWidth="2" />
      <circle cx={x} cy={y} r="3.6" fill={INK} />
    </g>
  );
}

const chordLine = (T, s0, s1) => { const a = T([s0, 0]), b = T([s1, 0]); return { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }; };
const DASHDOT = "14 5 2 5";

// ── Control reversal ─────────────────────────────────────────────────────
function Reversal({ id }) {
  const nose = 13, xp = 0.42, xac = 0.25, xh = 0.75, flapDeg = 22;
  const T = placer({ ox: 340, oy: 168, c: 350, xp, nose });
  const { body, flap, rot } = flappedPaths(T, xh, flapDeg);
  const [ax, ay] = T([xac, 0]);
  const [px, py] = T([xp, 0]);
  const [hx, hy] = T([xh, 0]);
  const te = T(rot([1, 0]));
  return (
    <svg viewBox="0 0 640 320" role="img" aria-label="Control reversal: aileron deflection adds lift but the moment about the flexural centre twists the wing nose-down" style={{ width: "100%", height: "auto", display: "block" }}>
      <Defs id={id} />
      <rect width="640" height="320" fill="#0d111c" />
      <Title>CONTROL REVERSAL</Title>
      <Freestream id={id} ys={[96, 130, 164, 198, 232]} />
      <line x1={150} y1={py} x2={612} y2={py} stroke={DIM} strokeWidth="1.3" strokeDasharray={DASHDOT} />
      <line {...chordLine(T, -0.4, 1.3)} stroke={DIM} strokeWidth="1.3" strokeDasharray={DASHDOT} />
      <line x1={ax} y1={ay} x2={ax} y2={300} stroke={DIM} strokeWidth="1.3" strokeDasharray={DASHDOT} />
      {/* α+θ */}
      <path d={arcPath(px, py, 214, 180, 180 + nose)} fill="none" stroke={INK} strokeWidth="1.6" markerStart={`url(#${id}-ink)`} markerEnd={`url(#${id}-ink)`} />
      <Label x={px - 196} y={py - 18} serif italic size={17}>α + θ</Label>
      {/* body + flap */}
      <path d={body} fill={BODY} stroke={INK} strokeWidth="2.2" strokeLinejoin="round" />
      <path d={flap} fill="#2a1c0e" stroke={FLAP} strokeWidth="2.2" strokeLinejoin="round" />
      <line x1={hx} y1={hy} x2={te[0]} y2={te[1]} stroke={FLAP} strokeWidth="1.2" strokeDasharray="5 4" />
      {/* ξ */}
      <path d={arcPath(hx, hy, 118, nose + 0.5, nose + flapDeg - 0.5)} fill="none" stroke={FLAP} strokeWidth="1.6" markerStart={`url(#${id}-flap)`} markerEnd={`url(#${id}-flap)`} />
      <Label x={hx + 128 * Math.cos(rad(nose + flapDeg / 2)) + 4} y={hy + 128 * Math.sin(rad(nose + flapDeg / 2)) + 6} serif italic size={19} color={FLAP}>ξ</Label>
      {/* support at the flexural centre */}
      <line x1={px} y1={py + 8} x2={px} y2={268} stroke={SPRING} strokeWidth="4" />
      <Ground id={id} x={px} y={268} />
      <Pivot x={px} y={py} />
      {/* loads at the aerodynamic centre */}
      <line x1={ax} y1={ay - 4} x2={ax} y2={34} stroke={FORCE} strokeWidth="3" markerEnd={`url(#${id}-force)`} />
      <Label x={ax + 12} y={46} size={18} weight={600} color={FORCE} serif>L + ΔL</Label>
      <Moment id={id} cx={ax} cy={ay} />
      <circle cx={ax} cy={ay} r="3.4" fill={FORCE} />
      <Label x={ax + 22} y={ay - 22} size={16} weight={600} color={FORCE} serif halo>M<tspan fontSize="11" dy="4">0</tspan><tspan dy="-4"> + ΔM</tspan><tspan fontSize="11" dy="4">0</tspan></Label>
      <Dimension id={id} x0={ax} x1={px} y={250} label="ec" />
      {/* labels */}
      <line x1={ax - 6} y1={ay + 10} x2={196} y2={281} stroke={DIM} strokeWidth="1" />
      <Label x={196} y={296} anchor="end" size={13} color={DIM}>aerodynamic centre</Label>
      <line x1={px + 8} y1={py - 8} x2={432} y2={96} stroke={DIM} strokeWidth="1" />
      <Label x={436} y={92} size={13} color={DIM}>flexural centre</Label>
    </svg>
  );
}

function Title({ children }) {
  return <text x={18} y={30} fill={DIM} fontFamily={SANS} fontSize="13" fontWeight="600" letterSpacing="1.5">{children}</text>;
}

// ── Static divergence: twist runs away ──────────────────────────────────
function Divergence({ id }) {
  const xp = 0.42, xac = 0.25;
  const stages = [3, 9, 16, 24];           // nose-up angle at increasing airspeed
  const base = { ox: 360, oy: 182, c: 330, xp };
  const Ts = stages.map((nose) => placer({ ...base, nose }));
  const T = Ts[Ts.length - 1];
  const [ax, ay] = T([xac, 0]);
  const [px, py] = T([xp, 0]);
  return (
    <svg viewBox="0 0 640 320" role="img" aria-label="Static divergence: lift ahead of the flexural centre twists the section further nose-up as airspeed rises, until the torsion spring can no longer hold it" style={{ width: "100%", height: "auto", display: "block" }}>
      <Defs id={id} />
      <rect width="640" height="320" fill="#0d111c" />
      <Title>STATIC DIVERGENCE</Title>
      <Freestream id={id} ys={[110, 144, 178, 212, 246]} />
      <line x1={150} y1={py} x2={620} y2={py} stroke={DIM} strokeWidth="1.3" strokeDasharray={DASHDOT} />
      {/* earlier, less-twisted stages */}
      {Ts.slice(0, -1).map((Ti, i) => (
        <path key={i} d={sectionPath(Ti)} fill="none" stroke={INK} strokeWidth="1.4"
          strokeDasharray="6 4" opacity={0.22 + 0.18 * i} />
      ))}
      <path d={sectionPath(T)} fill={BODY} stroke={INK} strokeWidth="2.4" strokeLinejoin="round" />
      {/* runaway twist arrow around the flexural centre */}
      <path d={arcPath(px, py, 205, 168, 214)} fill="none" stroke={FAIL} strokeWidth="3.2" markerEnd={`url(#${id}-fail)`} />
      <Label x={18} y={60} size={15} weight={600} color={FAIL}>twist grows</Label>
      <Label x={18} y={78} size={13} color={DIM}>as airspeed rises</Label>
      {/* torsion spring + support */}
      <line x1={px} y1={py + 19} x2={px} y2={276} stroke={SPRING} strokeWidth="4" />
      <Ground id={id} x={px} y={276} />
      <TorsionSpring cx={px} cy={py} />
      <Pivot x={px} y={py} />
      <Label x={px + 24} y={py + 40} serif italic size={17} color={SPRING}>k<tspan fontSize="12" dy="4">θ</tspan></Label>
      {/* lift at the aerodynamic centre */}
      <line x1={ax} y1={ay - 4} x2={ax} y2={40} stroke={FORCE} strokeWidth="3.2" markerEnd={`url(#${id}-force)`} />
      <Label x={ax + 12} y={54} size={18} weight={600} color={FORCE} serif italic>L</Label>
      <circle cx={ax} cy={ay} r="3.4" fill={FORCE} />
      <line x1={ax} y1={ay} x2={ax} y2={300} stroke={DIM} strokeWidth="1.3" strokeDasharray={DASHDOT} />
      <Dimension id={id} x0={ax} x1={px} y={258} label="ec" />
      <line x1={px + 12} y1={py - 8} x2={452} y2={92} stroke={DIM} strokeWidth="1" />
      <Label x={456} y={88} size={13} color={DIM}>flexural centre</Label>
      <line x1={ax - 5} y1={ay + 12} x2={214} y2={284} stroke={DIM} strokeWidth="1" />
      <Label x={214} y={299} anchor="end" size={13} color={DIM}>aerodynamic centre</Label>
    </svg>
  );
}

// ── Flutter: pitch + plunge oscillation that grows ──────────────────────
function Flutter({ id }) {
  const xp = 0.40, xcg = 0.56;
  const T = placer({ ox: 196, oy: 150, c: 210, xp, nose: 0 });
  const [px, py] = T([xp, 0]);
  const [gx, gy] = T([xcg, 0]);
  // trace of the elastic axis over time: plunge with growing amplitude,
  // pitch a quarter-cycle ahead of plunge (the classic flutter phasing)
  const x0 = 352, x1 = 612, yc = 150, cycles = 2.25;
  const amp = (t) => 8 + 66 * t * t;
  const trace = Array.from({ length: 160 }, (_, i) => {
    const t = i / 159; return [x0 + (x1 - x0) * t, yc + amp(t) * Math.sin(2 * Math.PI * cycles * t)];
  });
  const snaps = [0.111, 0.333, 0.556, 0.778, 1.0].map((t) => {
    const ph = 2 * Math.PI * cycles * t;
    // pitch leads plunge (shown 45° ahead so the tilt is visible at each crest)
    return { x: x0 + (x1 - x0) * t, y: yc + amp(t) * Math.sin(ph), pitch: (6 + 18 * t) * Math.sin(ph + Math.PI / 4), t };
  });
  return (
    <svg viewBox="0 0 640 320" role="img" aria-label="Flutter: a section on a plunge spring and a torsion spring oscillates in coupled pitch and plunge, and the oscillation grows over time" style={{ width: "100%", height: "auto", display: "block" }}>
      <Defs id={id} />
      <rect width="640" height="320" fill="#0d111c" />
      <Title>FLUTTER</Title>
      <Freestream id={id} x0={14} x1={70} ys={[112, 150, 188]} />
      {/* the section and its two springs */}
      <line x1={92} y1={py} x2={330} y2={py} stroke={DIM} strokeWidth="1.3" strokeDasharray={DASHDOT} />
      <path d={sectionPath(T)} fill={BODY} stroke={INK} strokeWidth="2.2" strokeLinejoin="round" />
      <CoilSpring x={px} y0={py + 16} y1={262} n={6} w={9} />
      <Ground id={id} x={px} y={262} w={48} />
      <TorsionSpring cx={px} cy={py} r0={4} r1={13} turns={1.9} />
      <Pivot x={px} y={py} />
      <g transform={`translate(${gx},${gy})`}>
        <circle r="6.5" fill={INK} />
        <path d="M0,-6.5 A6.5,6.5 0 0 1 6.5,0 L0,0 Z M0,6.5 A6.5,6.5 0 0 1 -6.5,0 L0,0 Z" fill="#0d111c" />
      </g>
      <Label x={px - 16} y={242} anchor="end" serif italic size={16} color={SPRING}>k<tspan fontSize="11" dy="4">h</tspan></Label>
      <Label x={px + 20} y={py + 34} serif italic size={16} color={SPRING}>k<tspan fontSize="11" dy="4">θ</tspan></Label>
      {/* the two freedoms */}
      <line x1={px - 92} y1={py - 34} x2={px - 92} y2={py + 34} stroke={FORCE} strokeWidth="2.2" markerStart={`url(#${id}-force)`} markerEnd={`url(#${id}-force)`} />
      <Label x={px - 104} y={py + 6} anchor="end" serif italic size={18} color={FORCE}>h</Label>
      <path d={arcPath(px, py, 112, -14, 14)} fill="none" stroke={FORCE} strokeWidth="2.2" markerStart={`url(#${id}-force)`} markerEnd={`url(#${id}-force)`} />
      <Label x={px + 124} y={py + 6} serif italic size={18} color={FORCE}>θ</Label>
      <Label x={px - 40} y={292} size={12} color={DIM}>plunge + pitch springs</Label>
      {/* over time: the coupled motion grows */}
      <line x1={x0} y1={yc} x2={x1 + 10} y2={yc} stroke={DIM} strokeWidth="1.2" strokeDasharray="3 5" />
      <path d={pathOf(trace, false)} fill="none" stroke={FAIL} strokeWidth="2" opacity="0.85" />
      {snaps.map((sn, i) => {
        const Ti = placer({ ox: sn.x, oy: sn.y, c: 64, xp: 0.4, nose: sn.pitch });
        return <path key={i} d={sectionPath(Ti)} fill={BODY} stroke={INK} strokeWidth="1.6" opacity={0.55 + 0.45 * sn.t} />;
      })}
      <line x1={x0} y1={296} x2={x1} y2={296} stroke={DIM} strokeWidth="1.3" markerEnd={`url(#${id}-dim)`} />
      <Label x={x1} y={288} anchor="end" size={12} color={DIM}>time</Label>
      <Label x={x0} y={48} size={15} weight={600} color={FAIL}>oscillation grows</Label>
      <Label x={x0} y={66} size={13} color={DIM}>pitch and plunge feed each other</Label>
    </svg>
  );
}

export default function AeroArt({ module }) {
  const id = "aa" + useId().replace(/[^a-zA-Z0-9]/g, "");
  if (module === "divergence") return <Divergence id={id} />;
  if (module === "reversal") return <Reversal id={id} />;
  return <Flutter id={id} />;
}
