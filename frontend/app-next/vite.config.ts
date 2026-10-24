import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Built into frontend/static/next/ (in the Docker assets stage); the backend
// serves index.html at /app for whitekobra only. `npm run dev` proxies /api.
export default defineConfig({
  base: "/static/next/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../static/next",
    emptyOutDir: true,
    target: "es2022",
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/lightweight-charts")) return "vendor-charts";
          if (id.includes("node_modules/motion") || id.includes("node_modules/framer-motion")) return "vendor-motion";
          if (id.includes("node_modules/react") || id.includes("node_modules/scheduler")) return "vendor-react";
        },
      },
    },
  },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
