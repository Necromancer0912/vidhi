import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// vercel.json is the single source for the production security headers and
// the backend address; the other hosts are derived from it.
const vercel = JSON.parse(readFileSync(new URL("./vercel.json", import.meta.url), "utf8"));
const productionHeaders = Object.fromEntries(
  vercel.headers.find((rule) => rule.source === "/(.*)").headers.map((h) => [h.key, h.value])
);
const backendOrigin = new URL(vercel.rewrites.find((r) => r.source.startsWith("/api")).destination.replace("$1", "")).origin;

// Cloudflare Pages sets CF_PAGES=1 during its builds. Pages can't proxy /api to
// an outside origin through config, so that build ships dist/_worker.js
// (cloudflare/worker.js) to proxy it and set the same security headers.
const onCloudflare = Boolean(process.env.CF_PAGES);

function cloudflareWorker() {
  let outDir = "dist";
  return {
    name: "cloudflare-worker",
    apply: "build",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      if (!onCloudflare) return;
      const worker = readFileSync(new URL("./cloudflare/worker.js", import.meta.url), "utf8")
        .replace("BACKEND_ORIGIN = __BACKEND_ORIGIN__;", `BACKEND_ORIGIN = ${JSON.stringify(backendOrigin)};`)
        .replace("SECURITY_HEADERS = __SECURITY_HEADERS__;", `SECURITY_HEADERS = ${JSON.stringify(productionHeaders, null, 2)};`);
      if (worker.includes("__BACKEND_ORIGIN__") || worker.includes("__SECURITY_HEADERS__")) {
        throw new Error("cloudflare/worker.js placeholders were not filled in");
      }
      writeFileSync(resolve(outDir, "_worker.js"), worker);
    },
  };
}

export default defineConfig({
  plugins: [react(), cloudflareWorker()],
  // On Cloudflare the worker proxies /api, so the app must use relative URLs even
  // if the Pages project still has a VITE_API_BASE_URL variable from older setups.
  define: onCloudflare ? { "import.meta.env.VITE_API_BASE_URL": JSON.stringify("") } : {},
  server: {
    port: 3000,
    host: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  // `npm run preview` serves the same security headers as production, so a
  // Content-Security-Policy violation shows up locally before deploy.
  preview: {
    headers: productionHeaders,
  },
  build: {
    outDir: "dist",
    assetsDir: "assets",
  },
});
