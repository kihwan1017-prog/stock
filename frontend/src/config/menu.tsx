"use client";

import type { ReactNode } from "react";
import {
  ApartmentOutlined,
  ApiOutlined,
  BarChartOutlined,
  BellOutlined,
  BulbOutlined,
  CloudServerOutlined,
  ControlOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FundOutlined,
  KeyOutlined,
  LineChartOutlined,
  MonitorOutlined,
  ReadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  StarOutlined,
  SwapOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UserOutlined,
  WalletOutlined,
} from "@ant-design/icons";

import {
  adminRoutes,
  userRoutes,
  type AdminRoute,
  type AppRoute,
  type UserRoute,
} from "@/config/routes";
import { isAdminRole, meetsUserMenuAccess } from "@/features/auth/utils/roles";

/**
 * 메뉴 항목 — path는 routes.ts의 캐노니컬 경로 타입만 허용한다.
 * USER/ADMIN 포털은 제네릭으로 분리해 서로 다른 경로가 섞이지 않게 한다.
 */
export interface AppMenuItem<TPath extends string = AppRoute> {
  key: string;
  label: string;
  path?: TPath;
  icon?: ReactNode;
  enabled: boolean;
  /** 메뉴 표시에 필요한 permission (없으면 로그인만 필요) */
  permission?: string;
  /**
   * User 메뉴 최소 접근 티어 (user 기본).
   * admin = 관리자 전용 메뉴 (현재 User 메뉴에서는 미사용)
   */
  minAccess?: "user" | "admin";
  children?: AppMenuItem<TPath>[];
}

export type AdminMenuItem = AppMenuItem<AdminRoute>;
export type UserMenuItem = AppMenuItem<UserRoute>;

/**
 * Admin 사이드바 메뉴 — 업무 흐름 순서(회원 → 계좌 → 시장데이터 → 전략·후보 →
 * 거래 → 리스크·운영 → 알림 → 운영관리 → 내 정보)로 구성한다.
 * M3-A: label/순서/monitoring 중복 노출만 정리. route·permission 불변.
 */
export const adminMenuItems: AdminMenuItem[] = [
  {
    key: "dashboard",
    label: "운영 대시보드",
    path: adminRoutes.dashboard,
    icon: <DashboardOutlined />,
    enabled: true,
    permission: "menu:dashboard",
  },
  {
    key: "members-group",
    label: "회원·권한",
    icon: <TeamOutlined />,
    enabled: true,
    children: [
      {
        key: "members",
        label: "회원관리",
        path: adminRoutes.members,
        icon: <UserOutlined />,
        enabled: true,
        permission: "menu:members",
      },
      {
        key: "roles",
        label: "권한관리",
        path: adminRoutes.roles,
        icon: <KeyOutlined />,
        enabled: true,
        permission: "menu:roles",
      },
    ],
  },
  {
    key: "accounts-group",
    label: "계좌",
    icon: <WalletOutlined />,
    enabled: true,
    children: [
      {
        key: "accounts",
        label: "전체 계좌",
        path: adminRoutes.accounts,
        icon: <WalletOutlined />,
        enabled: true,
        permission: "menu:accounts",
      },
      {
        key: "accounts-kiwoom",
        label: "키움 계좌",
        path: adminRoutes.kiwoom,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:kiwoom",
      },
      {
        key: "accounts-upbit",
        label: "업비트 계좌",
        path: adminRoutes.upbit,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:upbit",
      },
    ],
  },
  {
    key: "market-data",
    label: "시장 데이터",
    icon: <MonitorOutlined />,
    enabled: true,
    children: [
      {
        key: "upbit-market",
        label: "업비트 시세",
        path: adminRoutes.upbitMarkets,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:upbit",
      },
      {
        key: "indicators",
        label: "기술지표 관리",
        path: adminRoutes.indicators,
        icon: <LineChartOutlined />,
        enabled: true,
      },
      {
        key: "news",
        label: "뉴스 관리",
        path: adminRoutes.news,
        icon: <ReadOutlined />,
        enabled: true,
        permission: "menu:news",
      },
      {
        key: "disclosures",
        label: "공시 관리",
        path: adminRoutes.disclosures,
        icon: <FileTextOutlined />,
        enabled: true,
        permission: "menu:disclosures",
      },
    ],
  },
  {
    key: "strategy-ai",
    label: "전략·후보",
    icon: <ExperimentOutlined />,
    enabled: true,
    children: [
      {
        key: "strategies",
        label: "전략 관리",
        path: adminRoutes.strategies,
        icon: <ExperimentOutlined />,
        enabled: true,
        permission: "menu:strategies",
      },
      {
        key: "backtests",
        label: "백테스트",
        path: adminRoutes.backtests,
        icon: <BarChartOutlined />,
        enabled: true,
        permission: "menu:backtests",
      },
      {
        key: "ai",
        label: "후보·LLM 관리",
        path: adminRoutes.ai,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-providers",
        label: "Provider 관리",
        path: adminRoutes.aiProviders,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-prompts",
        label: "Prompt 관리",
        path: adminRoutes.aiPrompts,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-schemas",
        label: "Output Schema 관리",
        path: adminRoutes.aiSchemas,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-policies",
        label: "Policy 관리",
        path: adminRoutes.aiPolicies,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-executions",
        label: "Execution 관리",
        path: adminRoutes.aiExecutions,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-document-analyses",
        label: "문서 분석",
        path: adminRoutes.aiDocumentAnalyses,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-market-analyses",
        label: "시장·차트 분석",
        path: adminRoutes.aiMarketAnalyses,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-reviews",
        label: "Human Review",
        path: adminRoutes.aiReviews,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-evaluation-datasets",
        label: "Evaluation Dataset",
        path: adminRoutes.aiEvaluationDatasets,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-benchmarks",
        label: "Benchmark/Scorecard",
        path: adminRoutes.aiBenchmarks,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-candidate-assessments",
        label: "후보 평가 초안",
        path: adminRoutes.aiCandidateAssessments,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-candidate-consensuses",
        label: "Multi-AI 합의 초안",
        path: adminRoutes.aiCandidateConsensuses,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-candidate-recommendation-queues",
        label: "후보 추천 검토 큐",
        path: adminRoutes.aiCandidateRecommendationQueues,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-candidate-promotions",
        label: "Candidate Promotion Gateway",
        path: adminRoutes.aiCandidatePromotions,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "ai-candidate-lifecycle",
        label: "Candidate Lifecycle",
        path: adminRoutes.aiCandidateLifecycle,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
    ],
  },
  {
    key: "trading-group",
    label: "거래",
    icon: <SwapOutlined />,
    enabled: true,
    children: [
      {
        key: "trading",
        label: "자동매매관리",
        path: adminRoutes.trading,
        icon: <ThunderboltOutlined />,
        enabled: true,
        permission: "menu:trading",
      },
      {
        key: "orders",
        label: "주문관리",
        path: adminRoutes.orders,
        icon: <ApartmentOutlined />,
        enabled: true,
        permission: "menu:orders",
      },
      {
        key: "trades",
        label: "거래내역",
        path: adminRoutes.trades,
        icon: <FundOutlined />,
        enabled: true,
        permission: "menu:trades",
      },
      {
        key: "portfolio",
        label: "잔고·손익",
        path: adminRoutes.portfolio,
        icon: <FundOutlined />,
        enabled: true,
        permission: "menu:portfolio",
      },
    ],
  },
  {
    key: "risk-ops",
    label: "리스크·운영",
    icon: <SafetyCertificateOutlined />,
    enabled: true,
    children: [
      {
        key: "risk",
        label: "리스크 관리",
        path: adminRoutes.risk,
        icon: <SafetyCertificateOutlined />,
        enabled: true,
        permission: "menu:risk",
      },
      {
        key: "live-validation-upbit",
        label: "업비트 소액 LIVE 검증",
        path: adminRoutes.liveValidationUpbit,
        icon: <ThunderboltOutlined />,
        enabled: true,
        permission: "menu:risk",
      },
      {
        key: "operations",
        label: "운영센터",
        path: adminRoutes.operations,
        icon: <ControlOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
      {
        key: "operations-preflight",
        label: "Pre-flight Check",
        path: adminRoutes.operationsPreflight,
        icon: <SafetyCertificateOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
      {
        key: "operations-dashboard",
        label: "통합 모니터링",
        path: adminRoutes.operationsDashboard,
        icon: <DashboardOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
      {
        key: "scheduler",
        label: "스케줄러 관리",
        path: adminRoutes.scheduler,
        icon: <ControlOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
      {
        key: "batch",
        label: "배치 관리",
        path: adminRoutes.batch,
        icon: <CloudServerOutlined />,
        enabled: true,
        permission: "menu:batch",
      },
      {
        key: "recovery",
        label: "장애 복구",
        path: adminRoutes.recovery,
        icon: <ToolOutlined />,
        enabled: true,
      },
    ],
  },
  {
    key: "notifications-group",
    label: "알림",
    icon: <BellOutlined />,
    enabled: true,
    children: [
      {
        key: "notifications",
        label: "알림 관리",
        path: adminRoutes.notifications,
        icon: <BellOutlined />,
        enabled: true,
        permission: "menu:notifications",
      },
      {
        key: "telegram",
        label: "Telegram 운영",
        path: adminRoutes.telegram,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:notifications",
      },
    ],
  },
  {
    key: "system",
    label: "운영관리",
    icon: <SettingOutlined />,
    enabled: true,
    children: [
      {
        // M3-A: 시장 데이터 그룹의 동일 route 중복 노출 제거. page/route 유지.
        key: "system-monitoring",
        label: "시스템 모니터링",
        path: adminRoutes.monitoring,
        icon: <MonitorOutlined />,
        enabled: true,
        permission: "menu:monitoring",
      },
      {
        key: "system-settings",
        label: "시스템 설정",
        path: adminRoutes.systemSettings,
        icon: <SettingOutlined />,
        enabled: true,
        permission: "menu:system_settings",
      },
      {
        key: "env-settings",
        label: "환경설정",
        path: adminRoutes.envSettings,
        icon: <SettingOutlined />,
        enabled: true,
        permission: "menu:env_settings",
      },
      {
        key: "logs",
        label: "로그 조회",
        path: adminRoutes.logs,
        icon: <FileSearchOutlined />,
        enabled: true,
        permission: "menu:logs",
      },
      {
        key: "db",
        label: "DB 관리",
        path: adminRoutes.db,
        icon: <DatabaseOutlined />,
        enabled: true,
        permission: "menu:db",
      },
      {
        key: "api",
        label: "API 관리",
        path: adminRoutes.api,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:api",
      },
      {
        key: "ollama",
        label: "Ollama 관리",
        path: adminRoutes.ollama,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ollama",
      },
      {
        key: "documents-group",
        label: "문서관리",
        icon: <FileTextOutlined />,
        enabled: true,
        children: [
          {
            key: "docs",
            label: "문서 CMS",
            path: adminRoutes.docs,
            icon: <FileTextOutlined />,
            enabled: true,
            permission: "menu:docs",
          },
          {
            key: "docs-manual",
            label: "매뉴얼",
            path: adminRoutes.docsManual,
            icon: <ReadOutlined />,
            enabled: true,
            permission: "menu:docs",
          },
        ],
      },
    ],
  },
  {
    key: "my-info",
    label: "내 정보",
    icon: <UserOutlined />,
    enabled: true,
    children: [
      {
        key: "profile",
        label: "내 정보",
        path: adminRoutes.profile,
        icon: <UserOutlined />,
        enabled: true,
      },
    ],
  },
];

/** @deprecated adminMenuItems 사용 */
export const appMenuItems = adminMenuItems;

/** 평탄화된 메뉴 경로 목록 (권한 검사·selectedKey 계산용) */
export function flattenMenuItems<TPath extends string>(
  items: AppMenuItem<TPath>[],
): AppMenuItem<TPath>[] {
  const result: AppMenuItem<TPath>[] = [];
  for (const item of items) {
    if (item.children?.length) {
      result.push(...flattenMenuItems(item.children));
    } else if (item.path) {
      result.push(item);
    }
  }
  return result;
}

/** permission 기준으로 메뉴 트리 필터 */
export function filterMenuByPermissions<TPath extends string>(
  items: AppMenuItem<TPath>[],
  permissions: string[],
  roles: string[] = [],
): AppMenuItem<TPath>[] {
  const isAdmin = isAdminRole(roles);
  const owned = new Set(permissions);

  const filterNode = (
    item: AppMenuItem<TPath>,
  ): AppMenuItem<TPath> | null => {
    if (!item.enabled) {
      return null;
    }
    if (item.children?.length) {
      const children = item.children
        .map(filterNode)
        .filter((child): child is AppMenuItem<TPath> => child !== null);
      if (!children.length) {
        return null;
      }
      return { ...item, children };
    }
    if (
      item.permission &&
      !isAdmin &&
      !owned.has(item.permission)
    ) {
      return null;
    }
    return item;
  };

  return items
    .map(filterNode)
    .filter((item): item is AppMenuItem<TPath> => item !== null);
}

/** User 메뉴 최소 접근 티어로 필터 (user / admin) */
export function filterUserMenuByRoles<TPath extends string>(
  items: AppMenuItem<TPath>[],
  roles: string[],
): AppMenuItem<TPath>[] {
  const filterNode = (
    item: AppMenuItem<TPath>,
  ): AppMenuItem<TPath> | null => {
    if (!item.enabled) return null;
    if (item.children?.length) {
      const children = item.children
        .map(filterNode)
        .filter((child): child is AppMenuItem<TPath> => child !== null);
      if (!children.length) return null;
      return { ...item, children };
    }
    const minAccess = item.minAccess ?? "user";
    if (!meetsUserMenuAccess(roles, minAccess)) {
      return null;
    }
    return item;
  };

  return items
    .map(filterNode)
    .filter((item): item is AppMenuItem<TPath> => item !== null);
}

/** 경로에 매핑된 menu permission 조회 */
export function permissionForPath(
  pathname: string,
  items: AppMenuItem[] = adminMenuItems,
): string | undefined {
  const flat = flattenMenuItems(items);
  const exact = flat.find((item) => item.path === pathname);
  if (exact?.permission) {
    return exact.permission;
  }
  // 하위 경로 매칭 (가장 긴 path 우선)
  const matched = flat
    .filter((item) => item.path && pathname.startsWith(item.path))
    .sort((a, b) => (b.path?.length ?? 0) - (a.path?.length ?? 0));
  return matched[0]?.permission;
}

/**
 * User 사이드바 메뉴 — 업무 흐름 순서(대시보드 → 내 계좌 → 시장정보 →
 * 매매 후보 → 내 전략 → 내 주문·체결 → 잔고·손익 → 리스크 → 리포트 →
 * 알림 → 내 정보)로 구성한다.
 */
export const userMenuItems: UserMenuItem[] = [
  {
    key: "dashboard",
    label: "대시보드",
    path: userRoutes.dashboard,
    icon: <DashboardOutlined />,
    enabled: true,
    minAccess: "user",
  },
  {
    key: "my-accounts",
    label: "내 계좌",
    icon: <WalletOutlined />,
    enabled: true,
    children: [
      {
        key: "accounts-all",
        label: "전체 계좌",
        path: userRoutes.accounts,
        icon: <WalletOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "accounts-kiwoom",
        label: "키움 계좌",
        path: userRoutes.accountsKiwoom,
        icon: <ApiOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "accounts-upbit",
        label: "업비트 계좌",
        path: userRoutes.accountsUpbit,
        icon: <ApiOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "accounts-paper",
        label: "Paper 계좌",
        path: userRoutes.accountsPaper,
        icon: <WalletOutlined />,
        enabled: true,
        minAccess: "user",
      },
    ],
  },
  {
    key: "market-info",
    label: "시장 정보",
    icon: <LineChartOutlined />,
    enabled: true,
    children: [
      {
        key: "markets-stocks",
        label: "주식",
        path: userRoutes.marketsStocks,
        icon: <LineChartOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "markets-crypto",
        label: "암호화폐",
        path: userRoutes.marketsCrypto,
        icon: <LineChartOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "watchlist",
        label: "관심종목",
        path: userRoutes.watchlist,
        icon: <StarOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "news",
        label: "뉴스",
        path: userRoutes.news,
        icon: <ReadOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "disclosures",
        label: "공시",
        path: userRoutes.disclosures,
        icon: <FileTextOutlined />,
        enabled: true,
        minAccess: "user",
      },
    ],
  },
  {
    key: "candidates",
    label: "매매 후보",
    icon: <BulbOutlined />,
    enabled: true,
    children: [
      {
        key: "candidates-stocks",
        label: "주식 후보",
        path: userRoutes.candidatesStocks,
        icon: <BulbOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "candidates-crypto",
        label: "업비트 후보",
        path: userRoutes.candidatesCrypto,
        icon: <BulbOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "candidates-llm",
        label: "LLM 분석",
        path: userRoutes.candidatesLlm,
        icon: <RobotOutlined />,
        enabled: true,
        minAccess: "user",
      },
    ],
  },
  {
    key: "my-strategies",
    label: "내 전략",
    icon: <ExperimentOutlined />,
    enabled: true,
    children: [
      {
        key: "strategies",
        label: "전략",
        path: userRoutes.strategies,
        icon: <ExperimentOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "auto-trading",
        label: "자동매매",
        path: userRoutes.autoTrading,
        icon: <ThunderboltOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "backtests",
        label: "백테스트",
        path: userRoutes.backtests,
        icon: <BarChartOutlined />,
        enabled: true,
        minAccess: "user",
      },
    ],
  },
  {
    key: "live-validation-upbit",
    label: "업비트 LIVE 검증",
    path: userRoutes.liveValidationUpbit,
    icon: <ThunderboltOutlined />,
    enabled: true,
    minAccess: "user",
  },
  {
    key: "my-orders",
    label: "내 주문·체결",
    icon: <ApartmentOutlined />,
    enabled: true,
    children: [
      {
        key: "trading",
        label: "매매 실행",
        path: userRoutes.trading,
        icon: <SwapOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "orders",
        label: "주문·체결 내역",
        path: userRoutes.orders,
        icon: <ApartmentOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "orders-kiwoom",
        label: "키움 주문·체결",
        path: userRoutes.ordersKiwoom,
        icon: <ApiOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "orders-upbit",
        label: "업비트 주문·체결",
        path: userRoutes.ordersUpbit,
        icon: <ApiOutlined />,
        enabled: true,
        minAccess: "user",
      },
    ],
  },
  {
    key: "portfolio",
    label: "내 잔고·손익",
    path: userRoutes.portfolio,
    icon: <FundOutlined />,
    enabled: true,
    minAccess: "user",
  },
  {
    key: "risk",
    label: "내 리스크",
    path: userRoutes.risk,
    icon: <SafetyCertificateOutlined />,
    enabled: true,
    minAccess: "user",
  },
  {
    key: "reports",
    label: "내 리포트",
    path: userRoutes.reports,
    icon: <FileSearchOutlined />,
    enabled: true,
    minAccess: "user",
  },
  {
    key: "notifications",
    label: "알림",
    path: userRoutes.notifications,
    icon: <BellOutlined />,
    enabled: true,
    minAccess: "user",
  },
  {
    key: "my-info",
    label: "내 정보",
    icon: <UserOutlined />,
    enabled: true,
    children: [
      {
        key: "profile",
        label: "프로필",
        path: userRoutes.profile,
        icon: <UserOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        key: "settings",
        label: "설정",
        path: userRoutes.settings,
        icon: <SettingOutlined />,
        enabled: true,
        minAccess: "user",
      },
    ],
  },
];
