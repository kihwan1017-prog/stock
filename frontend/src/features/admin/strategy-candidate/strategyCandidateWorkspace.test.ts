import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { adminMenuItems, permissionForPath } from "@/config/menu";
import { adminRoutes } from "@/config/routes";
import {
  findStrategyCandidateWorkspace,
  resolveStrategyCandidateTabKey,
  STRATEGY_CANDIDATE_WORKSPACES,
} from "@/features/admin/strategy-candidate/strategyCandidateWorkspaceConfig";

/** vitest cwd = frontend/ */
const frontendRoot = process.cwd();

function readRel(rel: string): string {
  return readFileSync(join(frontendRoot, "src", rel), "utf8");
}

describe("STRATEGY_CANDIDATE UX consolidation", () => {
  it("사이드바 전략·후보 leaf는 5개 Workspace", () => {
    const analysis = adminMenuItems.find((item) => item.key === "analysis");
    const strategies = analysis?.children?.find((c) => c.key === "strategies");
    expect(strategies?.label).toBe("전략·후보");
    expect(strategies?.matchPaths).toEqual(
      expect.arrayContaining([
        adminRoutes.strategyCandidates,
        adminRoutes.strategyRequests,
        adminRoutes.strategyDrafts,
      ]),
    );
    const settings = adminMenuItems.find((item) => item.key === "settings");
    expect(
      settings?.children?.some((c) => c.key === "ai-config"),
    ).toBe(true);
    const advanced = adminMenuItems.find((item) => item.key === "advanced");
    expect(
      advanced?.children?.some((c) => c.key === "strategy-validation"),
    ).toBe(true);
  });

  it("구 leaf route는 page를 유지하고 Workspace matchPaths에 포함", () => {
    const covered = new Set(
      STRATEGY_CANDIDATE_WORKSPACES.flatMap((ws) => [...ws.matchPaths]),
    );
    const legacyRoutes = [
      adminRoutes.strategyRequests,
      adminRoutes.strategyDrafts,
      adminRoutes.portfolioValidations,
      adminRoutes.ai,
      adminRoutes.aiProviders,
      adminRoutes.aiPrompts,
      adminRoutes.aiSchemas,
      adminRoutes.aiPolicies,
      adminRoutes.aiExecutions,
      adminRoutes.aiDocumentAnalyses,
      adminRoutes.aiMarketAnalyses,
      adminRoutes.aiReviews,
      adminRoutes.aiEvaluationDatasets,
      adminRoutes.aiBenchmarks,
      adminRoutes.aiCandidateAssessments,
      adminRoutes.aiCandidateConsensuses,
      adminRoutes.aiCandidateRecommendationQueues,
      adminRoutes.aiCandidatePromotions,
      adminRoutes.aiCandidateLifecycle,
      adminRoutes.backtests,
    ];
    for (const route of legacyRoutes) {
      expect(covered.has(route)).toBe(true);
      const pagePath = join(
        frontendRoot,
        "src/app/(admin)",
        route.replace(/^\//, "") + "/page.tsx",
      );
      expect(readFileSync(pagePath, "utf8").length).toBeGreaterThan(10);
    }
  });

  it("workspace 해석: /admin/ai vs /admin/ai/providers 분리", () => {
    expect(findStrategyCandidateWorkspace(adminRoutes.ai)?.id).toBe("candidates");
    expect(findStrategyCandidateWorkspace(adminRoutes.aiProviders)?.id).toBe(
      "ai-config",
    );
    expect(
      findStrategyCandidateWorkspace(adminRoutes.strategyRequests)?.id,
    ).toBe("strategies");
    expect(
      findStrategyCandidateWorkspace(adminRoutes.aiMarketAnalyses)?.id,
    ).toBe("advanced");
  });

  it("tab key 해석", () => {
    const ws = findStrategyCandidateWorkspace(adminRoutes.aiPrompts)!;
    expect(resolveStrategyCandidateTabKey(ws, adminRoutes.aiPrompts)).toBe(
      "prompts",
    );
  });

  it("permissionForPath는 Workspace permission을 유지", () => {
    expect(permissionForPath(adminRoutes.aiPrompts)).toBe("menu:ai");
    expect(permissionForPath(adminRoutes.strategyRequests)).toBe(
      "menu:strategies",
    );
    expect(permissionForPath(adminRoutes.portfolioValidations)).toBe(
      "menu:backtests",
    );
  });

  it("Admin layout에 Workspace chrome이 연결된다", () => {
    const layout = readRel("app/(admin)/layout.tsx");
    expect(layout).toMatch(/StrategyCandidateWorkspaceChrome/);
  });

  it("업비트 자동매매 설정과 AI 전략 설정 역할 문구가 있다", () => {
    const ws = readRel(
      "features/admin/upbit/UpbitAutotradingSettingsWorkspace.tsx",
    );
    expect(ws).toMatch(/UBA별 LIVE Portfolio 운영 정책/);
    expect(ws).toMatch(/역할 구분/);
    const hub = adminMenuItems
      .find((item) => item.key === "autotrading")
      ?.children?.find((item) => item.key === "autotrading-upbit");
    expect(hub?.matchPaths).toContain(adminRoutes.upbitAutotrading);
  });

  it("authorization 완화 없음 — User 메뉴는 변경하지 않음", () => {
    const chrome = readRel(
      "features/admin/strategy-candidate/StrategyCandidateWorkspaceChrome.tsx",
    );
    expect(chrome).not.toMatch(/requiredRoles/);
    expect(chrome).not.toMatch(/hasPermission/);
  });
});
