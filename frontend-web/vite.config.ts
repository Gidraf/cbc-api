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
  // Shared between `server` and `preview`: the deployed console serves a built
  // bundle through `preview`, and an API that is only reachable in dev is an
  // API that works on a laptop and 502s in production.
  const proxy = Object.fromEntries(
    ["/api", "/admin", "/generate", "/auth", "/pipeline", "/health"].map((path) => [
      path,
      { target: proxyTarget, changeOrigin: true },
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
