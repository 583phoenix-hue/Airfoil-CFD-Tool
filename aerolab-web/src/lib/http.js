import { BACKEND_URL } from "../config.js";

/** Error with a message that can be shown to the user as-is. */
export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

function detailFrom(text, status) {
  try {
    const d = JSON.parse(text).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => e.msg || JSON.stringify(e)).join("; ");
  } catch { /* not JSON */ }
  if (/suspended/i.test(text)) return "The solver is unavailable right now (maintenance or monthly limit). Please try again later.";
  return text ? text.slice(0, 300) : `HTTP ${status}`;
}

/**
 * POST multipart form data to the backend.
 *   fields: plain object of form fields (numbers/booleans are stringified)
 *   file:   optional { name, content } (content: string | Blob)
 * Retries once on network errors / timeouts (Render cold start), never on 4xx.
 */
export async function postForm(path, fields, { file = null, timeoutMs = 120000, retries = 1, signal } = {}) {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) fd.append(k, typeof v === "string" ? v : String(v));
    if (file) {
      const blob = file.content instanceof Blob ? file.content : new Blob([file.content], { type: "text/plain" });
      fd.append("file", blob, file.name);
    }
    const ctrl = new AbortController();
    const onAbort = () => ctrl.abort();
    signal?.addEventListener("abort", onAbort);
    const timer = setTimeout(() => ctrl.abort("timeout"), timeoutMs);
    try {
      const res = await fetch(`${BACKEND_URL}${path}`, { method: "POST", body: fd, signal: ctrl.signal });
      const text = await res.text();
      if (!res.ok) {
        if (res.status === 503) {
          throw new ApiError(detailFrom(text, 503) + " (this feature isn't installed on the server yet).", 503);
        }
        throw new ApiError(detailFrom(text, res.status), res.status);
      }
      try {
        return JSON.parse(text);
      } catch {
        throw new ApiError("The server returned an unexpected response. Please try again.", res.status);
      }
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (signal?.aborted) throw new ApiError("Cancelled.");
      lastErr = ctrl.signal.aborted
        ? new ApiError("The request timed out. The solver may be busy or still waking up. Try again.")
        : new ApiError("Couldn't reach the solver. It may be starting up (about 30–60 s on the free tier).");
      if (attempt < retries) await new Promise((r) => setTimeout(r, 3000));
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }
  }
  throw lastErr;
}
