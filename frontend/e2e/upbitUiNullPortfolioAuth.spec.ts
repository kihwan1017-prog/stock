/**
 * Authenticated browser verify — UPBIT UI null / portfolio display (READ-ONLY).
 * E2E_ADMIN_USER / E2E_ADMIN_PASSWORD env 또는 로컬 bootstrap admin 사용.
 */
import { expect, test } from "@playwright/test";

const API_BASE =
  process.env.E2E_API_BASE_URL || "http://127.0.0.1:8000/api/v1";
const ADMIN_USER = process.env.E2E_ADMIN_USER || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "";

const CLOSED_ZERO_SYMBOLS = [
  "KRW-STX",
  "KRW-SUI",
  "KRW-WAVES",
  "KRW-ETC",
  "KRW-ONG",
  "KRW-SOL",
];

async function loginAccessToken(): Promise<string | null> {
  if (!ADMIN_PASSWORD) return null;
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      username: ADMIN_USER,
      password: ADMIN_PASSWORD,
    }),
  });
  if (!res.ok) return null;
  const data = (await res.json()) as { access_token?: string };
  return data.access_token ?? null;
}

async function seedAdminSession(page: import("@playwright/test").Page) {
  const token = await loginAccessToken();
  if (!token) {
    test.skip(true, "E2E_ADMIN_PASSWORD not set or login failed");
    return;
  }
  await page.addInitScript((accessToken: string) => {
    window.sessionStorage.setItem("kiki-admin-token", accessToken);
    document.cookie = `kiki-admin-token=${encodeURIComponent(accessToken)}; Path=/; SameSite=Lax`;
  }, token);
}

test.describe("UPBIT UI authenticated verify", () => {
  test.beforeEach(async ({ page }) => {
    await seedAdminSession(page);
  });

  test("/admin/upbit/autotrading — render + no precheck crash", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    await page.goto("/admin/upbit/autotrading", { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);

    expect(page.url()).not.toMatch(/\/login$/);
    const precheckCrash = [...pageErrors, ...consoleErrors].filter((m) =>
      m.includes("reading 'precheck'"),
    );
    expect(precheckCrash).toHaveLength(0);

    const body = await page.locator("body").innerText();
    expect(body).toMatch(/업비트|자동매매|24H|무인운영|LIVE|ARM/i);
  });

  test("/admin/portfolio — no 0E-8, closed zero hidden", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));

    await page.goto("/admin/portfolio", { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);

    expect(page.url()).not.toMatch(/\/login$/);
    const body = await page.locator("body").innerText();
    expect(body).not.toMatch(/0E-8/);
    expect(body).not.toMatch(/-0E-8/);

    for (const sym of CLOSED_ZERO_SYMBOLS) {
      expect(body).not.toContain(sym);
    }

    expect(body).toMatch(/보유|손익|평가|자동매매|일반매매/i);
    expect(pageErrors.length).toBe(0);
  });
});
