import { expect, test } from "@playwright/test";

/**
 * UPBIT UI null crash + portfolio display — browser smoke (READ-ONLY).
 * 인증 없이도 라우트·콘솔 fatal 오류를 확인한다.
 */
test.describe("UPBIT UI null / portfolio browser smoke", () => {
  test("admin upbit autotrading — no precheck null pageerror", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));
    const res = await page.goto("/admin/upbit/autotrading");
    expect(res?.status()).toBeLessThan(500);
    await page.waitForTimeout(2000);
    const precheckCrash = pageErrors.some((m) =>
      m.includes("reading 'precheck'"),
    );
    expect(precheckCrash).toBe(false);
  });

  test("admin portfolio — no scientific notation in visible body", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));
    const res = await page.goto("/admin/portfolio");
    expect(res?.status()).toBeLessThan(500);
    await page.waitForTimeout(2000);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/0E-8/);
    expect(bodyText).not.toMatch(/-0E-8/);
    expect(pageErrors.length).toBe(0);
  });
});
