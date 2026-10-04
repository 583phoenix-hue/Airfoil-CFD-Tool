// Backend URL: set VITE_BACKEND_URL at build time (Render env var) to point
// somewhere else, e.g. http://localhost:8000 for local development.
export const BACKEND_URL = (import.meta.env.VITE_BACKEND_URL || "https://aerolab-backend.onrender.com").replace(/\/$/, "");

export const COLORS = {
  bg: "#0a0d14", bgRaised: "#111623", bgCard: "#141a29",
  border: "#212a3d", borderStrong: "#2c3855",
  text: "#eef1f7", textDim: "#9aa4b8", textFaint: "#5c6683",
  c1: "#0000ff", c2: "#00ffff", c3: "#00ff00",
  c4: "#ffff00", c5: "#ff8000", c6: "#ff0000",
};
