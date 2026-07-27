import { defineConfig, devices } from "@playwright/test";

/**
 * FE/BE E2E 스캐폴드 (P2).
 * CI 기본 게이트에는 포함하지 않음 — 로컬/야간 잡에서 실행.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
