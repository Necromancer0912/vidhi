// Cloudflare Pages "advanced mode" worker, copied into dist/_worker.js by
// vite.config.js on Cloudflare builds. It does what vercel.json does on
// Vercel: proxies /api and /health to the backend (so the browser only ever
// talks to this origin) and applies the production security headers.
// The two constants below are filled in at build time from vercel.json.

const BACKEND_ORIGIN = __BACKEND_ORIGIN__;
const SECURITY_HEADERS = __SECURITY_HEADERS__;

function isBackendPath(pathname) {
  return pathname.startsWith("/api/") || pathname === "/health";
}

async function proxy(request) {
  const url = new URL(request.url);
  const headers = new Headers(request.headers);
  headers.delete("host");
  // The visitor's address, which the backend uses for per-visitor limits.
  // Set here, never taken from the caller.
  headers.set("x-client-ip", request.headers.get("cf-connecting-ip") || "");
  const hasBody = !["GET", "HEAD"].includes(request.method);
  return fetch(new URL(url.pathname + url.search, BACKEND_ORIGIN), {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    redirect: "manual",
  });
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (isBackendPath(pathname)) return proxy(request);

    const asset = await env.ASSETS.fetch(request);
    const response = new Response(asset.body, asset);
    for (const [name, value] of Object.entries(SECURITY_HEADERS)) response.headers.set(name, value);
    if (pathname.startsWith("/locales/")) response.headers.set("Cache-Control", "public, max-age=300, must-revalidate");
    return response;
  },
};
