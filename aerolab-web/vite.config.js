import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import os from "node:os";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  // Keep Vite's cache out of the project folder: OneDrive locks files in
  // node_modules/.vite while syncing, which causes "Access is denied".
  cacheDir: path.join(os.tmpdir(), "aerolab-web-vite-cache"),
  build: {
    // Plotly (charts) is ~1 MB but only loads on the tool pages.
    chunkSizeWarningLimit: 1200,
  },
});
