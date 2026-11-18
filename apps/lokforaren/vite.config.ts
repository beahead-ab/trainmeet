import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served by the hub (hub/web.py) at /lokforaren, where the meet's QR code leads (LOK-01,
// LOK-36). In development, `npm run dev` forwards /api to a hub running on port 8080.
export default defineConfig({
  base: "/lokforaren/",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:8080" } },
});
