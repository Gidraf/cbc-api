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
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/generate": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/questions": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/targets": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/review": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/human-review": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/production": {
          target: proxyTarget,
          changeOrigin: true
        },
        "/agents": {
          target: proxyTarget,
          changeOrigin: true
        }
      }
    }
  };
});
