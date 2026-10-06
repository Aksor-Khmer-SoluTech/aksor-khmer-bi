import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import pkg from "./package.json";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The in-app guides are the repo's /docs/*.md (src/docs/registry.ts), which sit
  // one level above this project root.
  server: { fs: { allow: [".."] } },
  build: {
    outDir: "dist",
  },
  // Surfaces package.json's version as a build-time constant (see
  // AboutDialog.tsx) rather than a second hardcoded copy of the number
  // that would drift from the real one.
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
});
