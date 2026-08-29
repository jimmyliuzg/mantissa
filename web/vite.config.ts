import { defineConfig } from "vite";
import preact from "@preact/preset-vite";
import { fileURLToPath, URL } from "node:url";

// Mantissa web is served from /<base>/ on GitHub Pages. The base path is
// read from VITE_BASE at build time, defaulting to "/" for local dev.
const base = process.env.VITE_BASE ?? "/";

export default defineConfig({
  base,
  plugins: [preact()],
  resolve: {
    alias: {
      "@engine": fileURLToPath(new URL("./src/engine/index.ts", import.meta.url)),
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
    outDir: "dist",
    emptyOutDir: true,
    // Mantissa's wheel + numpy wheel are large; don't pre-bundle them — let
    // the browser fetch them at runtime from the same origin (or CDN).
    rollupOptions: {
      output: {
        manualChunks: undefined,
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 8766,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 8766,
    strictPort: true,
  },
  // Keep tests close to source; vitest picks them up automatically.
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});
