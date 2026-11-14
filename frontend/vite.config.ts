import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import { execSync } from "child_process";

// one id per build: the bundle carries it (__BUILD_ID__) and /version.json serves it, so an open tab can tell a deploy
function gitSha(): string {
  try { return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim(); }
  catch { return "nogit"; }
}
const BUILD_ID = `${Date.now()}-${gitSha()}`;

// HUNTER_API_TARGET points a second dev server at another backend (e.g. http://127.0.0.1:8003)
const apiTarget = process.env.HUNTER_API_TARGET ?? "http://127.0.0.1:8002";

export default defineConfig({
  plugins: [react(), tailwindcss(), {
    name: "version-json",
    generateBundle() { this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ build: BUILD_ID }) }); },
  }],
  define: { __BUILD_ID__: JSON.stringify(BUILD_ID) },
  build: {
    outDir: path.resolve(__dirname, "../backend/static"),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        timeout: 180000,
      },
      "/ws": {
        target: apiTarget.replace(/^http/, "ws"),
        ws: true,
      },
    },
  },
});
