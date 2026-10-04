import { useEffect, useState } from "react";
import { checkBackend } from "./api.js";

// Shared across pages so navigating doesn't re-trigger the check each time.
let cached = { status: "checking", at: 0 };
const listeners = new Set();
let polling = null;

async function poll() {
  const status = await checkBackend();
  cached = { status, at: Date.now() };
  listeners.forEach((fn) => fn(status));
  // Keep checking until it's online (Streamlit made users refresh by hand).
  clearTimeout(polling);
  polling = setTimeout(poll, status === "online" ? 60000 : 10000);
}

export function useBackendStatus() {
  const [status, setStatus] = useState(cached.status);
  useEffect(() => {
    listeners.add(setStatus);
    if (cached.at === 0 || Date.now() - cached.at > 30000) poll();
    return () => listeners.delete(setStatus);
  }, []);
  return status;
}
