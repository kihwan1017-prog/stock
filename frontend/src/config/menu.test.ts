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

describe("single admin operator menu — ops-centric IA (WRK-008)", () => {
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

  it("최종 top-level 구조 (운영자 중심)", () => {
    expect(adminMenuItems.map((i) => i.key)).toEqual([
      "dashboard",
      "autotrading",
      "analysis",
      "settings",
      "ops-safety",
      "advanced",
    ]);
  });

  it("자동매매 leaf: 업비트/키움/주문/보유/일일보고/알림", () => {
    const auto = adminMenuItems.find((i) => i.key === "autotrading");
    expect(auto?.children?.map((c) => c.key)).toEqual([
      "autotrading-upbit",
      "autotrading-kiwoom",
      "orders",
      "portfolio",
      "autotrading-report",
      "notifications",
    ]);
  });

  it("설정에 계좌·리스크·AI 설정", () => {
    const grp = adminMenuItems.find((i) => i.key === "settings");
    expect(grp?.children?.map((c) => c.key)).toEqual([
      "accounts",
      "risk",
      "ai-config",
    ]);
  });

  it("고급 관리에 프로세스·검증·시스템 도구", () => {
    const adv = adminMenuItems.find((i) => i.key === "advanced");
    const keys = adv?.children?.map((c) => c.key) ?? [];
    expect(keys).toEqual(
      expect.arrayContaining([
        "autotrading-process",
        "llm-learning",
        "strategy-validation",
        "schedule-batch",
        "logs-audit",
        "data-api",
        "env-settings",
        "ai-infra",
        "docs",
      ]),
    );
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
    expect(strategies?.path).toBe(adminRoutes.strategyCandidates);
    expect(strategies?.matchPaths).toEqual(
      expect.arrayContaining([
        adminRoutes.strategyCandidates,
        adminRoutes.strategies,
        adminRoutes.strategyRequests,
        adminRoutes.strategyDrafts,
      ]),
    );
  });

  it("분석 그룹에 연구·AI·시장 데이터 포함", () => {
    const grp = adminMenuItems.find((i) => i.key === "analysis");
    const keys = grp?.children?.map((c) => c.key) ?? [];
    expect(keys).toEqual(
      expect.arrayContaining([
        "strategies",
        "market-analysis",
        "market-data",
        "news-disclosures",
        "ai-analysis",
        "research-data",
      ]),
    );
    expect(keys).not.toContain("llm-learning");
    expect(keys).not.toContain("ai-config");
    expect(keys).not.toContain("strategy-validation");
  });
});
