import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  adminMenuItems,
  flattenMenuItems,
  userMenuItems,
} from "@/config/menu";
import {
  adminRoutes,
  type AdminRoute,
} from "@/config/routes";

const frontendRoot = process.cwd();

function pageFileForRoute(route: string): string | null {
  if (route.startsWith("/admin/")) {
    return join(frontendRoot, "src/app/(admin)", route.slice(1), "page.tsx");
  }
  return null;
}

function duplicatePaths(paths: Array<string | undefined>): string[] {
  const seen = new Set<string>();
  const duplicates: string[] = [];
  for (const path of paths) {
    if (!path) continue;
    if (seen.has(path)) duplicates.push(path);
    seen.add(path);
  }
  return duplicates;
}

describe("single admin operator menu", () => {
  it("USER 사이드바는 비어 있다", () => {
    expect(userMenuItems).toHaveLength(0);
    expect(flattenMenuItems(userMenuItems)).toHaveLength(0);
  });

  it("ADMIN 메뉴 path는 adminRoutes만 사용한다", () => {
    const allowed = new Set<AdminRoute>(Object.values(adminRoutes));
    const paths = flattenMenuItems(adminMenuItems)
      .map((item) => item.path)
      .filter((path): path is AdminRoute => path !== undefined);
    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      expect(allowed.has(path), `unknown admin menu path: ${path}`).toBe(true);
      expect(path.startsWith("/admin")).toBe(true);
    }
  });

  it("회원·권한·내정보 메뉴가 없다", () => {
    const flat = flattenMenuItems(adminMenuItems);
    const labels = flat.map((i) => i.label);
    const keys = flat.map((i) => i.key);
    expect(labels.some((l) => l.includes("회원"))).toBe(false);
    expect(labels.some((l) => l.includes("권한관리"))).toBe(false);
    expect(keys).not.toContain("members");
    expect(keys).not.toContain("roles");
    expect(keys).not.toContain("profile");
  });

  it("최종 top-level 구조", () => {
    expect(adminMenuItems.map((i) => i.key)).toEqual([
      "dashboard",
      "accounts-assets",
      "autotrading",
      "strategy-analysis",
      "risk-safety",
      "notifications-group",
      "system",
    ]);
  });

  it("자동매매 leaf: 키움/업비트/주문·체결", () => {
    const auto = adminMenuItems.find((i) => i.key === "autotrading");
    expect(auto?.children?.map((c) => c.key)).toEqual([
      "autotrading-kiwoom",
      "autotrading-upbit",
      "orders",
    ]);
    expect(auto?.children?.map((c) => c.path)).toEqual([
      adminRoutes.autotradingKiwoom,
      adminRoutes.autotradingUpbit,
      adminRoutes.orders,
    ]);
  });

  it("계좌는 단일 현황 leaf + portfolio", () => {
    const grp = adminMenuItems.find((i) => i.key === "accounts-assets");
    expect(grp?.children?.map((c) => c.key)).toEqual([
      "accounts",
      "portfolio",
    ]);
  });

  it("사이드바 path 중복 없음", () => {
    expect(
      duplicatePaths(flattenMenuItems(adminMenuItems).map((i) => i.path)),
    ).toEqual([]);
  });

  it("monitoring 사이드바 1회", () => {
    const leaves = flattenMenuItems(adminMenuItems).filter(
      (i) => i.path === adminRoutes.monitoring,
    );
    expect(leaves).toHaveLength(1);
  });

  it("leaf page.tsx 존재", () => {
    const missing: string[] = [];
    for (const item of flattenMenuItems(adminMenuItems)) {
      if (!item.path) continue;
      const pageFile = pageFileForRoute(item.path);
      if (!pageFile || !existsSync(pageFile)) missing.push(item.path);
    }
    expect(missing).toEqual([]);
  });

  it("전략·후보 Workspace matchPaths 유지", () => {
    const strategies = flattenMenuItems(adminMenuItems).find(
      (i) => i.key === "strategies",
    );
    expect(strategies?.matchPaths).toEqual(
      expect.arrayContaining([
        adminRoutes.strategies,
        adminRoutes.strategyRequests,
        adminRoutes.strategyDrafts,
      ]),
    );
  });
});
