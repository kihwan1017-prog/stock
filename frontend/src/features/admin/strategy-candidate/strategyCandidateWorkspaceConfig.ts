/**
 * 전략·후보 Admin UX 통합 — 사이드바 5 Workspace + 내부 Tab 라우팅.
 * API/DB/페이지는 삭제하지 않고 navigation만 단순화한다.
 * Upbit FULL_MARKET_PORTFOLIO LIVE 경로와는 완전 분리 (이 설정은 UI 전용).
 */

import { adminRoutes, type AdminRoute } from "@/config/routes";

export type StrategyCandidateWorkspaceId =
  | "strategies"
  | "candidates"
  | "ai-config"
  | "validation"
  | "advanced";

export type StrategyCandidateTab = {
  key: string;
  label: string;
  href: AdminRoute;
};

export type StrategyCandidateWorkspace = {
  id: StrategyCandidateWorkspaceId;
  /** 사이드바·크롬 제목 */
  label: string;
  description: string;
  /** 사이드바 leaf path (= 기본 진입) */
  homePath: AdminRoute;
  /** 사이드바 선택/권한 매칭에 쓰는 경로 (home 포함) */
  matchPaths: readonly AdminRoute[];
  /** 메뉴 permission (없으면 Admin role만) */
  permission?: string;
  tabs: readonly StrategyCandidateTab[];
};

export const STRATEGY_CANDIDATE_WORKSPACES: readonly StrategyCandidateWorkspace[] =
  [
    {
      id: "strategies",
      label: "전략 관리",
      description:
        "전략 생성부터 검토·승인·배포까지 관리합니다. (STEP12 전략 lifecycle)",
      homePath: adminRoutes.strategies,
      permission: "menu:strategies",
      matchPaths: [
        adminRoutes.strategies,
        adminRoutes.strategyRequests,
        adminRoutes.strategyDrafts,
      ],
      tabs: [
        { key: "strategies", label: "전략", href: adminRoutes.strategies },
        {
          key: "requests",
          label: "전략 요청",
          href: adminRoutes.strategyRequests,
        },
        { key: "drafts", label: "전략 초안", href: adminRoutes.strategyDrafts },
      ],
    },
    {
      id: "candidates",
      label: "후보 관리",
      description:
        "시장/AI에서 생성된 전략 후보와 Candidate lifecycle을 관리합니다. UPBIT Scanner LIVE 후보는 「업비트 자동매매 설정」에서 별도 관리합니다.",
      homePath: adminRoutes.aiCandidateLifecycle,
      permission: "menu:ai",
      matchPaths: [
        adminRoutes.ai,
        adminRoutes.aiCandidateLifecycle,
        adminRoutes.aiCandidatePromotions,
        adminRoutes.aiCandidateAssessments,
        adminRoutes.aiCandidateConsensuses,
        adminRoutes.aiCandidateRecommendationQueues,
      ],
      tabs: [
        {
          key: "lifecycle",
          label: "Candidate Lifecycle",
          href: adminRoutes.aiCandidateLifecycle,
        },
        {
          key: "screener",
          label: "후보·LLM (Screener)",
          href: adminRoutes.ai,
        },
        {
          key: "promotions",
          label: "Promotion",
          href: adminRoutes.aiCandidatePromotions,
        },
        {
          key: "assessments",
          label: "평가 초안",
          href: adminRoutes.aiCandidateAssessments,
        },
        {
          key: "consensuses",
          label: "Multi-AI 합의",
          href: adminRoutes.aiCandidateConsensuses,
        },
        {
          key: "queues",
          label: "추천 검토 큐",
          href: adminRoutes.aiCandidateRecommendationQueues,
        },
      ],
    },
    {
      id: "ai-config",
      label: "AI 전략 설정",
      description:
        "전략 생성·분석에 사용하는 AI Provider, Model, Prompt, Policy를 관리합니다. UBA별 LIVE 운영 정책은 「업비트 자동매매 설정」을 사용하세요.",
      homePath: adminRoutes.aiProviders,
      permission: "menu:ai",
      matchPaths: [
        adminRoutes.aiProviders,
        adminRoutes.aiPrompts,
        adminRoutes.aiSchemas,
        adminRoutes.aiPolicies,
        adminRoutes.aiExecutions,
      ],
      tabs: [
        { key: "providers", label: "Provider", href: adminRoutes.aiProviders },
        { key: "prompts", label: "Prompt", href: adminRoutes.aiPrompts },
        { key: "schemas", label: "Output Schema", href: adminRoutes.aiSchemas },
        { key: "policies", label: "Policy", href: adminRoutes.aiPolicies },
        {
          key: "executions",
          label: "Execution",
          href: adminRoutes.aiExecutions,
        },
      ],
    },
    {
      id: "validation",
      label: "전략 검증",
      description:
        "Backtest, Portfolio 검증 및 AI 평가 결과를 관리합니다. LIVE 코인 선택에는 직접 연결되지 않습니다.",
      homePath: adminRoutes.backtests,
      permission: "menu:backtests",
      matchPaths: [
        adminRoutes.backtests,
        adminRoutes.portfolioValidations,
        adminRoutes.aiEvaluationDatasets,
        adminRoutes.aiBenchmarks,
      ],
      tabs: [
        { key: "backtests", label: "Backtest", href: adminRoutes.backtests },
        {
          key: "portfolio",
          label: "Portfolio 검증",
          href: adminRoutes.portfolioValidations,
        },
        {
          key: "datasets",
          label: "Evaluation Dataset",
          href: adminRoutes.aiEvaluationDatasets,
        },
        {
          key: "benchmarks",
          label: "Benchmark/Score",
          href: adminRoutes.aiBenchmarks,
        },
      ],
    },
    {
      id: "advanced",
      label: "고급 관리",
      description:
        "Human Review, 분석 도구 및 감사 기능을 관리합니다. 일상 운영보다 연구·감사용입니다.",
      homePath: adminRoutes.aiReviews,
      permission: "menu:ai",
      matchPaths: [
        adminRoutes.aiReviews,
        adminRoutes.aiDocumentAnalyses,
        adminRoutes.aiMarketAnalyses,
      ],
      tabs: [
        { key: "reviews", label: "Human Review", href: adminRoutes.aiReviews },
        {
          key: "documents",
          label: "문서 분석",
          href: adminRoutes.aiDocumentAnalyses,
        },
        {
          key: "market",
          label: "시장·차트 분석",
          href: adminRoutes.aiMarketAnalyses,
        },
      ],
    },
  ] as const;

/** 후보 Workspace: /admin/ai 단독만 매칭 — /admin/ai/providers 등은 AI 설정 Workspace */
export function pathnameMatchesWorkspacePath(
  pathname: string,
  path: string,
): boolean {
  if (pathname === path) return true;
  if (path === adminRoutes.ai) {
    return false;
  }
  return pathname.startsWith(`${path}/`);
}

/** pathname이 전략·후보 Workspace에 속하면 해당 Workspace 반환 */
export function findStrategyCandidateWorkspace(
  pathname: string,
): StrategyCandidateWorkspace | null {
  let best: StrategyCandidateWorkspace | null = null;
  let bestLen = -1;
  for (const workspace of STRATEGY_CANDIDATE_WORKSPACES) {
    for (const path of workspace.matchPaths) {
      if (pathnameMatchesWorkspacePath(pathname, path)) {
        if (path.length > bestLen) {
          best = workspace;
          bestLen = path.length;
        }
      }
    }
  }
  return best;
}

/** Workspace 내 활성 Tab key */
export function resolveStrategyCandidateTabKey(
  workspace: StrategyCandidateWorkspace,
  pathname: string,
): string {
  let bestKey = workspace.tabs[0]?.key ?? "";
  let bestLen = -1;
  for (const tab of workspace.tabs) {
    if (pathnameMatchesWorkspacePath(pathname, tab.href)) {
      if (tab.href.length > bestLen) {
        bestKey = tab.key;
        bestLen = tab.href.length;
      }
    }
  }
  return bestKey;
}
