import { expect, test } from "@playwright/test";

/**
 * 스모크: 로그인 페이지가 뜨는지 확인.
 * 본격 시나리오(로그인→Paper 주문→Kill Switch)는 BE/FE 동시 기동 후 확장.
 */
test.describe("auth smoke", () => {
  test("login page renders", async ({ page }) => {
    await page.goto("/login");
    await expect(page).toHaveURL(/login/);
    // 브랜드/폼 중 하나라도 보이면 OK
    const body = page.locator("body");
    await expect(body).toBeVisible();
  });
});
