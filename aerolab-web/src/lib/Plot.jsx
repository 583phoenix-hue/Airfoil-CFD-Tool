import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { COLORS } from "../config.js";

// Plotly is ~1 MB gzipped, so it is loaded only when the first chart mounts
// (the home/about pages never download it).
let plotlyPromise = null;
export function loadPlotly() {
  if (!plotlyPromise) plotlyPromise = import("plotly.js-basic-dist-min").then((m) => m.default || m);
  return plotlyPromise;
}

/** Same look as the Streamlit pages' _style(): dark card background, grid, legend under the chart. */
export function chartLayout({ xTitle, yTitle, height = 340, equal = false, reverseY = false, legend = true,
  hovermode = "closest", shapes = [], annotations = [], yRange, xRange, title } = {}) {
  const axis = { gridcolor: COLORS.border, zeroline: false, linecolor: COLORS.border, automargin: true,
    tickfont: { color: COLORS.textDim }, title: { font: { color: COLORS.textDim } } };
  const layout = {
    height,
    hovermode,
    plot_bgcolor: COLORS.bgCard,
    paper_bgcolor: COLORS.bgCard,
    font: { color: COLORS.textDim, family: "Inter, system-ui, sans-serif", size: 12 },
    margin: { t: title ? 40 : legend ? 30 : 12, b: 10, l: 10, r: 10 },
    showlegend: legend,
    // legend above the plot area so it never collides with the x-axis title
    legend: { orientation: "h", yanchor: "bottom", y: 1.01, xanchor: "right", x: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...axis, title: { ...axis.title, text: xTitle }, ...(xRange ? { range: xRange } : {}) },
    yaxis: { ...axis, title: { ...axis.title, text: yTitle }, ...(yRange ? { range: yRange } : {}) },
    shapes,
    annotations,
  };
  if (title) layout.title = { text: title, font: { color: COLORS.text, size: 14 }, x: 0.02 };
  if (equal) { layout.yaxis.scaleanchor = "x"; layout.yaxis.scaleratio = 1; }
  if (reverseY) layout.yaxis.autorange = "reversed";
  return layout;
}

// Label positions for up to four marker lines, staggered so neighbours don't collide.
const VLINE_SLOTS = [
  { y: 1, yanchor: "top", xanchor: "left" },
  { y: 1, yanchor: "top", xanchor: "right" },
  { y: 0.9, yanchor: "top", xanchor: "left" },
  { y: 0.9, yanchor: "top", xanchor: "right" },
];

/** Vertical marker line with a label, like Plotly-Python's add_vline(annotation_text=...). */
export function vline(x, label, color, dash = "solid", slot = 0) {
  if (x === null || x === undefined || !Number.isFinite(x)) return { shapes: [], annotations: [] };
  const pos = VLINE_SLOTS[slot % 4];
  return {
    shapes: [{ type: "line", xref: "x", yref: "paper", x0: x, x1: x, y0: 0, y1: 1,
      line: { color, width: 1.5, dash } }],
    annotations: [{ x, xref: "x", yref: "paper", ...pos, text: label, showarrow: false,
      font: { color, size: 11 }, bgcolor: "rgba(20,26,41,0.85)", xshift: pos.xanchor === "left" ? 4 : -4 }],
  };
}

export function hline(y, color = COLORS.borderStrong, dash = "dash") {
  return { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: y, y1: y, line: { color, width: 1, dash } };
}

/**
 * Several labelled vertical lines on one chart, laid out so their labels never
 * overlap: sorted by x, the left half put their label on the left of the line
 * and the right half on the right, and each label sits on its own row.
 * items: [x, label, color, dash?]   (missing / non-finite x are skipped)
 */
export function vlines(items) {
  const list = items.filter(([x]) => x !== null && x !== undefined && Number.isFinite(x)).sort((a, b) => a[0] - b[0]);
  const out = { shapes: [], annotations: [] };
  list.forEach(([x, label, color, dash = "solid"], i) => {
    const leftSide = list.length > 1 && i < list.length / 2;
    out.shapes.push({ type: "line", xref: "x", yref: "paper", x0: x, x1: x, y0: 0, y1: 1, line: { color, width: 1.5, dash } });
    out.annotations.push({
      x, xref: "x", yref: "paper", y: 1 - 0.09 * i, yanchor: "top",
      xanchor: leftSide ? "right" : "left", xshift: leftSide ? -4 : 4,
      text: label, showarrow: false, font: { color, size: 11 }, bgcolor: "rgba(20,26,41,0.85)",
    });
  });
  return out;
}

/** Merge several {shapes, annotations} decorations into one. */
export function decorations(...parts) {
  return parts.reduce((acc, p) => ({
    shapes: acc.shapes.concat(p.shapes || (p.type ? [p] : [])),
    annotations: acc.annotations.concat(p.annotations || []),
  }), { shapes: [], annotations: [] });
}

const CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"],
  toImageButtonOptions: { format: "png", scale: 2 },
};

/**
 * <Plot data={...} layout={...} title="..." />
 * `title` is drawn above the chart as text (long Plotly titles were truncated
 * and hard to read on the dark background in the Streamlit version).
 * The ref exposes downloadPng(filename).
 */
const Plot = forwardRef(function Plot({ data, layout, title, style, filename = "aerolab_chart" }, ref) {
  const el = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    loadPlotly()
      .then((Plotly) => {
        if (cancelled || !el.current) return;
        Plotly.react(el.current, data, layout,
          { ...CONFIG, toImageButtonOptions: { ...CONFIG.toImageButtonOptions, filename } });
      })
      .catch(() => setError("Charts couldn't load. Check your connection and refresh."));
    return () => { cancelled = true; };
  }, [data, layout, filename]);

  useEffect(() => () => {
    const node = el.current;
    if (node && plotlyPromise) plotlyPromise.then((P) => P.purge(node)).catch(() => {});
  }, []);

  useImperativeHandle(ref, () => ({
    async downloadPng(name) {
      const P = await loadPlotly();
      await P.downloadImage(el.current, { format: "png", filename: name || filename, scale: 2,
        width: 900, height: layout?.height || 400 });
    },
  }), [filename, layout]);

  return (
    <div className="chart" style={style}>
      {title && <div className="chart-title">{title}</div>}
      {error ? <div className="alert alert-error">{error}</div>
        : <div ref={el} style={{ width: "100%", minHeight: layout?.height || 340 }} />}
    </div>
  );
});

export default Plot;

/**
 * Download a line chart styled like the old matplotlib exports: white
 * background, black axes with only left/bottom spines, dashed grey grid,
 * #667eea line with round markers, two-line centred title.
 * (Only the downloaded file looks like this; the on-page chart keeps the
 * dark theme.)
 */
export async function downloadMplPng({ x, y, title, subtitle, xLabel, yLabel, filename }) {
  const P = await loadPlotly();
  const font = { family: "DejaVu Sans, Verdana, Arial, sans-serif", color: "#000000", size: 13 };
  const axis = (text) => ({
    title: { text, font: { ...font, size: 14 }, standoff: 10 },
    showline: true, linecolor: "#000000", linewidth: 1, mirror: false,
    ticks: "outside", tickcolor: "#000000", ticklen: 5, tickfont: font,
    showgrid: true, gridcolor: "rgba(128,128,128,0.5)", griddash: "dash", gridwidth: 1,
    zeroline: false, automargin: true,
  });
  const fig = {
    data: [{ x, y, mode: "lines+markers", line: { color: "#667eea", width: 2.5 },
      marker: { color: "#667eea", size: 7 }, hoverinfo: "skip" }],
    layout: {
      width: 900, height: 600, paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff", font,
      showlegend: false, margin: { l: 80, r: 30, t: 80, b: 70 },
      title: { text: `${title}<br>${subtitle}`, x: 0.5, xanchor: "center", y: 0.95, font: { ...font, size: 15 } },
      xaxis: axis(xLabel), yaxis: axis(yLabel),
    },
  };
  await P.downloadImage(fig, { format: "png", filename, width: 900, height: 600, scale: 2 });
}
