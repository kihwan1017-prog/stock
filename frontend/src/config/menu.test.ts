import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  adminMenuItems,
  flattenMenuItems,
  userMenuItems,
} from "@/config/menu";
import {
  adminRoutes,
  getRouteTitle,
  type AdminRoute,
  type UserRoute,
  userRoutes,
} from "@/config/routes";

/** vitest cwd = frontend/ */
const frontendRoot = process.cwd();

function pageFileForRoute(route: string): string | null {
  if (route.startsWith("/admin/")) {
    return join(frontendRoot, "src/app/(admin)", route.slice(1), "page.tsx");
  }
  if (route.startsWith("/user/")) {
    return join(frontendRoot, "src/app/(user)", route.slice(1), "page.tsx");
  }
  return null;
}

function duplicatePaths(paths: Array<string | undefined>): string[] {
  const seen = new Set<string>();
  const duplicates: string[] = [];
  for (const path of paths) {
    if (!path) continue;
    if (seen.has(path)) {
      duplicates.push(path);
    }
    seen.add(path);
  }
  return duplicates;
}

describe("menu link validity (STEP7)", () => {
  it("USER 메뉴의 모든 path는 userRoutes 값이어야 한다", () => {
    const allowed = new Set<UserRoute>(Object.values(userRoutes));
    const paths = flattenMenuItems(userMenuItems)
      .map((item) => item.path)
      .filter((path): path is UserRoute => path !== undefined);

    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      expect(allowed.has(path), `unknown user menu path: ${path}`).toBe(true);
      expect(path.startsWith("/user") || path.startsWith("/login")).toBe(true);
    }
  });

  it("ADMIN 메뉴의 모든 path는 adminRoutes 값이어야 한다", () => {
    const allowed = new Set<AdminRoute>(Object.values(adminRoutes));
    const paths = flattenMenuItems(adminMenuItems)
      .map((item) => item.path)
      .filter((path): path is AdminRoute => path !== undefined);

    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      expect(allowed.has(path), `unknown admin menu path: ${path}`).toBe(true);
      expect(path.startsWith("/admin") || path.startsWith("/login")).toBe(true);
    }
  });

  it("USER·ADMIN 메뉴가 서로 섞이지 않는다", () => {
    const userPaths = flattenMenuItems(userMenuItems).map((i) => i.path);
    const adminPaths = flattenMenuItems(adminMenuItems).map((i) => i.path);
    for (const path of userPaths) {
      if (!path) continue;
      expect(path.startsWith("/admin")).toBe(false);
    }
    for (const path of adminPaths) {
      if (!path) continue;
      expect(path.startsWith("/user")).toBe(false);
    }
  });

  it("M4-B 사이드바 카운트: Admin 11/40, User 12/29", () => {
    expect(adminMenuItems).toHaveLength(11);
    // 전략·후보 Workspace 통합(21→5 leaf) 후 Admin leaf=40
    expect(flattenMenuItems(adminMenuItems)).toHaveLength(40);
    expect(userMenuItems).toHaveLength(12);
    expect(flattenMenuItems(userMenuItems)).toHaveLength(29);
  });

  it("ADMIN·USER 사이드바에 동일 path가 중복 노출되지 않는다", () => {
    expect(duplicatePaths(flattenMenuItems(adminMenuItems).map((item) => item.path))).toEqual([]);
    expect(duplicatePaths(flattenMenuItems(userMenuItems).map((item) => item.path))).toEqual([]);
  });

  it("/admin/monitoring 사이드바 노출은 1회다", () => {
    const monitoringLeaves = flattenMenuItems(adminMenuItems).filter(
      (item) => item.path === adminRoutes.monitoring,
    );
    expect(monitoringLeaves).toHaveLength(1);
    expect(monitoringLeaves[0]?.key).toBe("system-monitoring");
  });

  it("M3-B 전략 workflow route는 유지되고 Admin 사이드바는 Workspace 5개로 통합된다", () => {
    const adminFlat = flattenMenuItems(adminMenuItems);
    const userFlat = flattenMenuItems(userMenuItems);

    // Admin: 개별 leaf 제거 — Workspace matchPaths로 커버
    expect(adminFlat.find((item) => item.path === adminRoutes.strategyRequests)).toBeUndefined();
    expect(adminFlat.find((item) => item.path === adminRoutes.strategyDrafts)).toBeUndefined();
    expect(
      adminFlat.find((item) => item.path === adminRoutes.portfolioValidations),
    ).toBeUndefined();

    const strategiesWs = adminFlat.find((item) => item.key === "strategies");
    expect(strategiesWs?.matchPaths).toEqual(
      expect.arrayContaining([
        adminRoutes.strategies,
        adminRoutes.strategyRequests,
        adminRoutes.strategyDrafts,
      ]),
    );

    const userRequest = userFlat.find((item) => item.path === userRoutes.strategyRequests);
    const userDraft = userFlat.find((item) => item.path === userRoutes.strategyDrafts);
    expect(userRequest?.key).toBe("strategy-requests");
    expect(userDraft?.key).toBe("strategy-drafts");

    expect(adminRoutes.strategyRequests).toBe("/admin/strategy-requests");
    expect(adminRoutes.strategyDrafts).toBe("/admin/strategy-drafts");
    expect(adminRoutes.portfolioValidations).toBe("/admin/portfolio-validations");
    expect(userRoutes.strategyRequests).toBe("/user/strategy-requests");
    expect(userRoutes.strategyDrafts).toBe("/user/strategy-drafts");

    expect(userRequest?.minAccess).toBe("user");
    expect(userDraft?.minAccess).toBe("user");

    // User에는 Admin 전용 Portfolio Validation route를 만들지 않는다.
    expect(userFlat.some((item) => item.path?.includes("portfolio-validations"))).toBe(
      false,
    );

    const adminStrategyGroup = adminMenuItems.find((item) => item.key === "strategy-ai");
    expect(adminStrategyGroup?.children?.map((item) => item.key)).toEqual([
      "strategies",
      "strategy-candidates",
      "strategy-ai-config",
      "strategy-validation",
      "strategy-advanced",
    ]);
    expect(adminStrategyGroup?.children).toHaveLength(5);

    const userStrategyGroup = userMenuItems.find((item) => item.key === "my-strategies");
    expect(userStrategyGroup?.children?.slice(0, 3).map((item) => item.key)).toEqual([
      "strategies",
      "strategy-requests",
      "strategy-drafts",
    ]);

    expect(getRouteTitle(adminRoutes.strategyRequests)).toBe("전략 요청");
    expect(getRouteTitle(adminRoutes.strategyDrafts)).toBe("전략 초안");
    expect(getRouteTitle(adminRoutes.portfolioValidations)).toBe("포트폴리오 검증");
    expect(getRouteTitle(userRoutes.strategyRequests)).toBe("전략 요청");
    expect(getRouteTitle(userRoutes.strategyDrafts)).toBe("전략 초안");

    // page.tsx backward compatibility
    expect(existsSync(pageFileForRoute(adminRoutes.strategyRequests)!)).toBe(true);
    expect(existsSync(pageFileForRoute(adminRoutes.strategyDrafts)!)).toBe(true);
    expect(existsSync(pageFileForRoute(adminRoutes.portfolioValidations)!)).toBe(true);
  });

  it("M4-A 운영 canonical route와 메뉴 label이 유지된다", () => {
    const adminFlat = flattenMenuItems(adminMenuItems);
    const byKey = (key: string) => adminFlat.find((item) => item.key === key);

    expect(byKey("operations")?.path).toBe("/admin/operations");
    expect(byKey("operations")?.label).toBe("시스템 운영");
    expect(byKey("trading")?.path).toBe("/admin/trading");
    expect(byKey("trading")?.label).toBe("자동매매 Runtime");
    expect(byKey("operations-dashboard")?.path).toBe("/admin/operations-dashboard");
    expect(byKey("operations-dashboard")?.label).toBe("거래 운영 현황");
    expect(byKey("system-monitoring")?.path).toBe("/admin/monitoring");
    expect(byKey("recovery")?.path).toBe("/admin/recovery");
    expect(byKey("risk")?.path).toBe("/admin/risk");
    expect(byKey("orders")?.path).toBe("/admin/orders");
    expect(byKey("scheduler")?.path).toBe("/admin/scheduler");
    expect(byKey("operations-preflight")?.path).toBe("/admin/operations/preflight");
    expect(byKey("operations")?.permission).toBe("menu:scheduler");
    expect(byKey("trading")?.permission).toBe("menu:trading");
  });

  it("M4-B 운영 메뉴 regroup: 자동매매 운영 / 시스템 운영 / 리스크·안전", () => {
    const topKeys = adminMenuItems.map((item) => item.key);
    expect(topKeys).toContain("autotrading-ops");
    expect(topKeys).toContain("system");
    expect(topKeys).toContain("risk-ops");

    const autotrading = adminMenuItems.find((item) => item.key === "autotrading-ops");
    const system = adminMenuItems.find((item) => item.key === "system");
    const risk = adminMenuItems.find((item) => item.key === "risk-ops");
    const trading = adminMenuItems.find((item) => item.key === "trading-group");

    expect(autotrading?.label).toBe("자동매매 운영");
    expect(system?.label).toBe("시스템 운영");
    expect(risk?.label).toBe("리스크·안전");

    expect(autotrading?.children?.map((item) => item.key)).toEqual([
      "operations-dashboard",
      "trading",
      "upbit-autotrading",
      "operations-preflight",
    ]);
    expect(autotrading?.children?.map((item) => item.path)).toEqual([
      "/admin/operations-dashboard",
      "/admin/trading",
      "/admin/upbit/autotrading",
      "/admin/operations/preflight",
    ]);

    expect(system?.children?.slice(0, 5).map((item) => item.key)).toEqual([
      "operations",
      "system-monitoring",
      "scheduler",
      "recovery",
      "batch",
    ]);
    expect(system?.children?.find((item) => item.key === "operations")?.path).toBe(
      "/admin/operations",
    );
    expect(system?.children?.find((item) => item.key === "system-monitoring")?.path).toBe(
      "/admin/monitoring",
    );
    expect(system?.children?.find((item) => item.key === "scheduler")?.path).toBe(
      "/admin/scheduler",
    );
    expect(system?.children?.find((item) => item.key === "scheduler")?.label).toBe(
      "시스템 스케줄러",
    );
    expect(system?.children?.find((item) => item.key === "recovery")?.path).toBe(
      "/admin/recovery",
    );

    expect(risk?.children?.map((item) => item.key)).toEqual([
      "risk",
      "live-validation-upbit",
    ]);
    expect(risk?.children?.find((item) => item.key === "risk")?.path).toBe("/admin/risk");

    // Orders는 거래 그룹 유지. LIVE UBA 중복 leaf 없음.
    expect(trading?.children?.map((item) => item.key)).toEqual([
      "orders",
      "trades",
      "portfolio",
    ]);
    expect(trading?.children?.find((item) => item.key === "orders")?.path).toBe(
      "/admin/orders",
    );
    const liveControlLeaves = flattenMenuItems(adminMenuItems).filter(
      (item) => item.label === "계좌 LIVE 제어",
    );
    expect(liveControlLeaves).toHaveLength(0);

    // User 메뉴는 M4-B에서 변경하지 않는다.
    expect(userMenuItems).toHaveLength(12);
    expect(flattenMenuItems(userMenuItems)).toHaveLength(29);
  });

  it("사이드바 leaf path에 대응하는 page.tsx가 존재한다", () => {
    const leaves = [
      ...flattenMenuItems(adminMenuItems),
      ...flattenMenuItems(userMenuItems),
    ];
    const missing: string[] = [];
    for (const item of leaves) {
      if (!item.path) continue;
      const pageFile = pageFileForRoute(item.path);
      if (!pageFile || !existsSync(pageFile)) {
        missing.push(item.path);
      }
    }
    expect(missing).toEqual([]);
  });

  it("M7-A User LLM 메뉴는 /user/ai canonical을 가리키고 llm redirect는 유지한다", () => {
    const userFlat = flattenMenuItems(userMenuItems);
    const llmLeaves = userFlat.filter((item) => item.key === "candidates-llm");
    expect(llmLeaves).toHaveLength(1);
    expect(llmLeaves[0]?.path).toBe(userRoutes.ai);
    expect(llmLeaves[0]?.path).toBe("/user/ai");
    expect(llmLeaves[0]?.label).toBe("LLM 분석");

    // 메뉴에 legacy llm path 없음
    expect(userFlat.some((item) => item.path === userRoutes.candidatesLlm)).toBe(false);
    expect(userFlat.some((item) => item.path === "/user/candidates/llm")).toBe(false);

    // /user/ai leaf 1회 · duplicate 0
    expect(userFlat.filter((item) => item.path === userRoutes.ai)).toHaveLength(1);
    expect(duplicatePaths(userFlat.map((item) => item.path))).toEqual([]);

    const aiPage = pageFileForRoute(userRoutes.ai);
    const llmPage = pageFileForRoute(userRoutes.candidatesLlm);
    expect(aiPage && existsSync(aiPage)).toBe(true);
    expect(llmPage && existsSync(llmPage)).toBe(true);

    // redirect page 계약: /user/candidates/llm → userRoutes.ai
    const llmSource = readFileSync(llmPage!, "utf8");
    expect(llmSource).toMatch(/redirect\s*\(\s*userRoutes\.ai\s*\)/);
    expect(userRoutes.candidatesLlm).toBe("/user/candidates/llm");
    expect(userRoutes.ai).toBe("/user/ai");

    // M3-B / Admin leaf 회귀 없음 (샘플)
    expect(userFlat.find((item) => item.path === userRoutes.strategyRequests)?.key).toBe(
      "strategy-requests",
    );
    expect(userFlat.find((item) => item.path === userRoutes.strategyDrafts)?.key).toBe(
      "strategy-drafts",
    );
    // Admin strategy-requests는 Workspace Tab으로 이동 — leaf 없음, route/page 유지
    expect(
      flattenMenuItems(adminMenuItems).find(
        (item) => item.path === adminRoutes.strategyRequests,
      ),
    ).toBeUndefined();
    expect(
      flattenMenuItems(adminMenuItems)
        .find((item) => item.key === "strategies")
        ?.matchPaths?.includes(adminRoutes.strategyRequests),
    ).toBe(true);
  });
});
