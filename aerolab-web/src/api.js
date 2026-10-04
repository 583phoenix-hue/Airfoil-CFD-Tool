import { BACKEND_URL } from "./config.js";

/**
 * Backend health, as seen from the student's own browser.
 *   "online"      -- /health answered
 *   "waking"      -- no answer within the timeout: Render's free tier is
 *                    spinning the backend up after inactivity (30-60 s)
 *   "unavailable" -- the request failed quickly without an answer. Render's
 *                    "service suspended" page has no CORS headers, so the
 *                    browser can't read it; a fast failure is the best signal.
 */
export async function checkBackend(timeoutMs = 8000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const started = performance.now();
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { signal: ctrl.signal, cache: "no-store" });
    if (res.ok) return "online";
    const text = await res.text().catch(() => "");
    if (/suspended/i.test(text)) return "unavailable";
    return "waking";
  } catch (err) {
    if (err.name === "AbortError") return "waking";
    return performance.now() - started < 3000 ? "unavailable" : "waking";
  } finally {
    clearTimeout(timer);
  }
}

export async function getAnalysisCount() {
  try {
    const res = await fetch(`${BACKEND_URL}/analysis_count`, { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    return typeof data.count === "number" ? data.count : null;
  } catch {
    return null;
  }
}
