import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { adminRoutes } from "@/config/routes";

/** vitest cwd = frontend/ */
const frontendRoot = process.cwd();
const srcRoot = join(frontendRoot, "src");

function walkTsxFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === ".next") continue;
      walkTsxFiles(full, out);
    } else if (name.endsWith(".tsx") || name.endsWith(".ts")) {
      out.push(full);
    }
  }
  return out;
}

function readRel(pathFromSrc: string): string {
  return readFileSync(join(srcRoot, pathFromSrc), "utf8");
}

describe("M4-C AdminUpbitLiveUbaPanel single-mount", () => {
  it("production mount는 /admin/accounts 1회만", () => {
    const files = walkTsxFiles(srcRoot);
    const mounts: string[] = [];
    for (const file of files) {
      if (file.includes(".test.") || file.includes(".spec.")) continue;
      const text = readFileSync(file, "utf8");
      if (!text.includes("AdminUpbitLiveUbaPanel")) continue;
      // JSX mount만 카운트 (import/export 제외)
      if (/<AdminUpbitLiveUbaPanel\b/.test(text)) {
        mounts.push(file.replace(/\\/g, "/"));
      }
    }
    expect(mounts).toHaveLength(1);
    expect(mounts[0]).toContain("app/(admin)/admin/accounts/page.tsx");
  });

  it("/admin/upbit에는 panel 없고 READ summary + accounts link가 있다", () => {
    const page = readRel("app/(admin)/admin/upbit/page.tsx");
    expect(page).not.toMatch(/AdminUpbitLiveUbaPanel/);
    expect(page).toMatch(/UpbitLiveStatusReadSummary/);
    expect(page).toMatch(/adminRoutes\.accounts/);
    expect(page).toMatch(/계좌 관리 \(LIVE\/ARM 제어\)/);

    // HIGH-risk LIVE/ARM/Scheduler mutation 경로 없음
    expect(page).not.toMatch(/setAdminLiveOrderEnabled/);
    expect(page).not.toMatch(/armAdminLiveOrder/);
    expect(page).not.toMatch(/disarmAdminLiveOrder/);
    expect(page).not.toMatch(/startTradingScheduler/);
    expect(page).not.toMatch(/pauseTradingScheduler/);

    // Upbit ops panels 유지
    expect(page).toMatch(/UpbitOpportunityScannerPanel/);
    expect(page).toMatch(/UpbitNewsCombinedShadowPanel/);
    expect(page).toMatch(/UpbitNewsNoticeCollectorPanel/);
    expect(page).toMatch(/UpbitAmbiguousOrdersPanel/);
  });

  it("READ summary는 GET만 사용하고 LIVE mutation을 import하지 않는다", () => {
    const summary = readRel(
      "features/admin/upbit/UpbitLiveStatusReadSummary.tsx",
    );
    expect(summary).toMatch(/listAdminBrokerAccounts/);
    expect(summary).toMatch(/getAdminLiveOpsReadiness/);
    expect(summary).toMatch(/getTradingSchedulerStatus/);
    expect(summary).toMatch(/adminRoutes\.accounts/);
    expect(summary).toMatch(/adminRoutes\.recovery/);
    expect(summary).not.toMatch(/setAdminLiveOrderEnabled/);
    expect(summary).not.toMatch(/armAdminLiveOrder/);
    expect(summary).not.toMatch(/disarmAdminLiveOrder/);
    expect(summary).not.toMatch(/startTradingScheduler/);
    expect(summary).not.toMatch(/pauseTradingScheduler/);
    expect(summary).not.toMatch(/useMutation/);
  });

  it("accounts page는 panel을 유지한다", () => {
    const page = readRel("app/(admin)/admin/accounts/page.tsx");
    expect(page).toMatch(/<AdminUpbitLiveUbaPanel\s*\/>/);
  });

  it("M3/M4 menu regression: monitoring=1, duplicate=0, strategy visible", () => {
    const flat = flattenMenuItems(adminMenuItems);
    const paths = flat.map((item) => item.path).filter(Boolean) as string[];
    const seen = new Set<string>();
    const dup: string[] = [];
    for (const p of paths) {
      if (seen.has(p)) dup.push(p);
      seen.add(p);
    }
    expect(dup).toEqual([]);
    expect(
      flat.filter((item) => item.path === adminRoutes.monitoring),
    ).toHaveLength(1);
    expect(flat.some((item) => item.path === adminRoutes.strategyRequests)).toBe(
      true,
    );
    expect(flat.some((item) => item.path === adminRoutes.strategyDrafts)).toBe(
      true,
    );
    expect(
      flat.some((item) => item.path === adminRoutes.portfolioValidations),
    ).toBe(true);
  });

  it("accounts·upbit·recovery page.tsx 존재", () => {
    for (const route of [
      adminRoutes.accounts,
      adminRoutes.upbit,
      adminRoutes.recovery,
    ]) {
      const page = join(
        frontendRoot,
        "src/app/(admin)",
        route.slice(1),
        "page.tsx",
      );
      expect(existsSync(page), page).toBe(true);
    }
  });
});
