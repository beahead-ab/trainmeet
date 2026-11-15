import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The web app is served by ID's API (id/app.py) from dist/. In development, `npm run dev`
// forwards /api to an ID's API running on port 8002.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:8002" } },
});
