import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// F4.1 — SPA build do web/static/spa (FastAPI mount /spa, base '/spa/').
export default defineConfig({
  plugins: [react()],
  base: "/spa/",
  build: {
    outDir: "../src/stopa/web/static/spa",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // dev server proxy → běžíící FastAPI (uvicorn :8042)
      "/api": "http://localhost:8042",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
