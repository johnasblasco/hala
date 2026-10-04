import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` on :5173 proxies API calls to `hala serve` on :8000.
// Build: locally, output goes into the Python package so `hala serve` can serve it.
// On Vercel (VERCEL=1 at build time) the "web" service deploys its own dist/.
export default defineConfig({
  plugins: [react()],
  build: process.env.VERCEL
    ? { outDir: "dist" }
    : { outDir: "../hala/static", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/reports": "http://localhost:8000",
      "/preview": "http://localhost:8000",
    },
  },
});
