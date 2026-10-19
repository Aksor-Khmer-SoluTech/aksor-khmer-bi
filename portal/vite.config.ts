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
    rollupOptions: {
      output: {
        // React and the code editor change only on a dependency upgrade, so they get their own chunks: a release that
        // touches only the portal's own code leaves them cached in the browser.
        manualChunks(id) {
          if (!id.includes("/node_modules/")) return undefined;
          if (/\/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "react";
          if (/\/node_modules\/(@codemirror|@lezer|@marijn|style-mod|w3c-keyname|crelt)\//.test(id)) return "codemirror";
          // Without this each icon shared by two pages becomes a chunk of its own: dozens of sub-kilobyte requests.
          if (id.includes("/node_modules/lucide-react/")) return "icons";
          return undefined;
        },
      },
    },
  },
  // Surfaces package.json's version as a build-time constant (see
  // AboutDialog.tsx) rather than a second hardcoded copy of the number
  // that would drift from the real one.
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
});
