import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served by TKL's own server (tkl/app.py) at /. In development, `npm run dev` forwards /api to
// a TKL running on port 8090 (`uv run python -m tkl`).
export default defineConfig({
  base: "/",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:8090" } },
});
