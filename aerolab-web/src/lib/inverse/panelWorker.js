// Helper worker for inverse design: evaluates batches of the optimiser's
// residual (one panel-method solve each) so the finite-difference Jacobian
// is spread over several CPU cores. It talks to the design worker over the
// MessagePort it is handed by the page (inverseClient.js).
//   port in:  { type: "setup", spec } | { type: "eval", id, tgt, points }
//   port out: { id, out }  (one residual array per point)
import { makeResiduals } from "./inverse.js";

self.onmessage = (ev) => {
  const { port } = ev.data;
  let residuals = null;
  port.onmessage = (e) => {
    const d = e.data;
    if (d.type === "setup") { residuals = makeResiduals(d.spec); return; }
    port.postMessage({ id: d.id, out: d.points.map((p) => residuals(p, d.tgt)) });
  };
};
