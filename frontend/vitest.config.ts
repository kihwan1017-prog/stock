import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    env: {
      NEXT_PUBLIC_APP_NAME: "KIKI AI Trading Platform",
      NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8000",
      NEXT_PUBLIC_API_PREFIX: "/api/v1",
      NEXT_PUBLIC_WS_BASE_URL: "ws://127.0.0.1:8000",
      NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS: "false",
      NEXT_PUBLIC_AUTH_MODE: "backend",
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
