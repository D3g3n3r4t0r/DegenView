import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Built into frontend/static/next/ (in the Docker assets stage); the backend
// serves index.html at /app for whitekobra only. `npm run dev` proxies /api.
export default defineConfig({
  base: "/static/next/",
  plugins: [react(), tailwindcss()],
  build: { outDir: "../static/next", emptyOutDir: true, target: "es2022" },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
