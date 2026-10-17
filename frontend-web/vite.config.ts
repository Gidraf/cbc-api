import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { defineConfig, loadEnv } from "vite";

const root = dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.API_PROXY_TARGET || "http://localhost:8000";

  // Only paths the app actually calls are proxied. `/questions` and `/review`
  // used to be proxied too, which shadowed the client routes of the same name —
  // navigating to /questions returned raw API JSON instead of the page. The
  // console calls those endpoints under /api/v1.
  //
  // Each key is an ANCHORED REGEX, not a bare prefix. A bare prefix matches by
  // string, so `/pipeline` also swallowed `/pipelines` — the pipeline board's
  // own client route — and a refresh on that page returned {"detail":"Not
  // Found"} from the API while clicking through to it from the sidebar worked,
  // because only the refresh is a server request. `(/|$)` requires the prefix
  // to end at a path boundary, so a client route can never again be shadowed
  // by an API prefix that merely starts the same way. The boundary includes
  // `?` because the proxy matches the request URL, query string and all, and
  // `/health?verbose=1` is the same endpoint as `/health`.
  //
  // Shared between `server` and `preview`: the deployed console serves a built
  // bundle through `preview`, and an API that is only reachable in dev is an
  // API that works on a laptop and 502s in production.
  const API_PREFIXES = ["/api", "/admin", "/generate", "/auth", "/pipeline", "/health", "/p"];
  const proxy = Object.fromEntries(
    API_PREFIXES.map((path) => [
      `^${path}(?:[/?]|$)`,
      // `xfwd` sends X-Forwarded-Host/Proto with the address the browser
      // used. With changeOrigin the API sees Host: api:8000 — the compose
      // service name — and a link it wrote for a download read
      // http://api:8000/…, which resolves nowhere outside the box.
      { target: proxyTarget, changeOrigin: true, xfwd: true },
    ])
  );

  return {
    root,
    server: {
      host: "0.0.0.0",
      port: 5173,
      // Without this, any absolute path the module graph asks for is read off
      // the container filesystem, and a path that does not exist there surfaces
      // as a full-screen ENOENT overlay covering the console. Confined to the
      // project, an out-of-tree request is a clean 403 instead.
      fs: {
        strict: true,
        allow: [root],
      },
      watch: {
        ignored: [
          "**/broadcast/**",
          "**/deployments/**",
          "**/artifacts/**",
          "**/out/**",
          "**/.git/**",
        ],
      },
      proxy,
    },
    preview: {
      host: "0.0.0.0",
      port: 5173,
      proxy,
      // The deployed console's headers. Scripts only from this site and the
      // KaTeX CDN the paper previews load (their onload handler is inline,
      // hence 'unsafe-inline' for scripts — no other site can run code here);
      // nothing may frame the console but itself.
      headers: {
        "Content-Security-Policy": [
          "default-src 'self'",
          "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
          "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
          "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com",
          "img-src 'self' data: blob: https:",
          "media-src 'self' blob: https:",
          "connect-src 'self'",
          "frame-src 'self' blob: data:",
          "worker-src 'self' blob:",
          "object-src 'none'",
          "base-uri 'self'",
          "form-action 'self'",
          "frame-ancestors 'self'",
        ].join("; "),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Frame-Options": "SAMEORIGIN",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
      },
    },
    build: {
      // Source maps make a production stack trace readable without shipping a
      // dev server to do it.
      sourcemap: true,
    },
    resolve: {
      alias: {
        "@": resolve(root, "src"),
      },
    },
  };
});
