import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.API_PROXY_TARGET || "http://localhost:8000";

  return {
    server: {
      host: "0.0.0.0",
      port: 5173,
      watch: {
        ignored: [
          "**/broadcast/**",
          "**/deployments/**",
          "**/artifacts/**",
          "**/out/**",
          "**/.git/**"
        ]
      },
      // Only paths the app actually calls are proxied. `/questions` and
      // `/review` used to be proxied too, which shadowed the client routes of
      // the same name — navigating to /questions returned raw API JSON instead
      // of the page. The console calls those endpoints under /api/v1.
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/admin": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/generate": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/auth": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/pipeline": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/health": {
          target: proxyTarget,
          changeOrigin: true
        }
      }
    }
  };
});
