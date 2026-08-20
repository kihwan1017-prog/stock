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
  /**
   * 사이드바 선택·권한 매칭용 추가 경로 (Workspace 통합 시).
   * leaf path 외 하위 화면 bookmark를 부모 Workspace에 귀속시킨다.
   */
  matchPaths?: readonly TPath[];
  children?: AppMenuItem<TPath>[];
}

export type AdminMenuItem = AppMenuItem<AdminRoute>;
export type UserMenuItem = AppMenuItem<UserRoute>;

/**
 * Admin 사이드바 메뉴 — 업무 흐름 순서(회원 → 계좌 → 시장데이터 → 전략·후보 →
 * 자동매매 운영 → 거래 → 리스크·안전 → 알림 → 시스템 운영 → 내 정보).
 * M4-B: 운영 메뉴 regroup만. route·permission·page 불변. monitoring sidebar=1.
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
    // STRATEGY_CANDIDATE_MENU UX: 세부 화면은 Workspace Tab으로 이동.
    // 기존 route/page/API는 유지 (사이드바 leaf만 5개로 축소).
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
        matchPaths: [
          adminRoutes.strategies,
          adminRoutes.strategyRequests,
          adminRoutes.strategyDrafts,
        ],
      },
      {
        key: "strategy-candidates",
        label: "후보 관리",
        path: adminRoutes.aiCandidateLifecycle,
        icon: <BulbOutlined />,
        enabled: true,
        permission: "menu:ai",
        matchPaths: [
          adminRoutes.ai,
          adminRoutes.aiCandidateLifecycle,
          adminRoutes.aiCandidatePromotions,
          adminRoutes.aiCandidateAssessments,
          adminRoutes.aiCandidateConsensuses,
          adminRoutes.aiCandidateRecommendationQueues,
        ],
      },
      {
        key: "strategy-ai-config",
        label: "AI 전략 설정",
        path: adminRoutes.aiProviders,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
        matchPaths: [
          adminRoutes.aiProviders,
          adminRoutes.aiPrompts,
          adminRoutes.aiSchemas,
          adminRoutes.aiPolicies,
          adminRoutes.aiExecutions,
        ],
      },
      {
        key: "strategy-validation",
        label: "전략 검증",
        path: adminRoutes.backtests,
        icon: <BarChartOutlined />,
        enabled: true,
        permission: "menu:backtests",
        matchPaths: [
          adminRoutes.backtests,
          adminRoutes.portfolioValidations,
          adminRoutes.aiEvaluationDatasets,
          adminRoutes.aiBenchmarks,
        ],
      },
      {
        key: "strategy-advanced",
        label: "고급 관리",
        path: adminRoutes.aiReviews,
        icon: <ToolOutlined />,
        enabled: true,
        permission: "menu:ai",
        matchPaths: [
          adminRoutes.aiReviews,
          adminRoutes.aiDocumentAnalyses,
          adminRoutes.aiMarketAnalyses,
        ],
      },
    ],
  },
  {
    // M4-B: Runtime/Preflight/거래현황 — CONTROL/READ ownership은 각 page 유지.
    key: "autotrading-ops",
    label: "자동매매 운영",
    icon: <ThunderboltOutlined />,
    enabled: true,
    children: [
      {
        key: "operations-dashboard",
        label: "거래 운영 현황",
        path: adminRoutes.operationsDashboard,
        icon: <DashboardOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
      {
        key: "trading",
        label: "자동매매 Runtime",
        path: adminRoutes.trading,
        icon: <ThunderboltOutlined />,
        enabled: true,
        permission: "menu:trading",
      },
      {
        key: "upbit-autotrading",
        label: "업비트 자동매매 설정",
        path: adminRoutes.upbitAutotrading,
        icon: <SettingOutlined />,
        enabled: true,
        permission: "menu:upbit",
      },
      {
        key: "operations-preflight",
        label: "Pre-flight Check",
        path: adminRoutes.operationsPreflight,
        icon: <SafetyCertificateOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
    ],
  },
  {
    // 주문·체결·잔고는 자동매매 운영과 분리 (중복 leaf 금지).
    key: "trading-group",
    label: "거래",
    icon: <SwapOutlined />,
    enabled: true,
    children: [
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
    // Risk/Kill canonical 유지. LIVE UBA leaf는 계좌 메뉴에 이미 있으므로 추가하지 않음.
    key: "risk-ops",
    label: "리스크·안전",
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
    // Launchpad + infra/ops. UBA Trading Scheduler와 구분하기 위해 scheduler label 명확화.
    key: "system",
    label: "시스템 운영",
    icon: <ControlOutlined />,
    enabled: true,
    children: [
      {
        key: "operations",
        label: "시스템 운영",
        path: adminRoutes.operations,
        icon: <ControlOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
      {
        // M3-A: monitoring sidebar 1회 유지.
        key: "system-monitoring",
        label: "시스템 모니터링",
        path: adminRoutes.monitoring,
        icon: <MonitorOutlined />,
        enabled: true,
        permission: "menu:monitoring",
      },
      {
        key: "scheduler",
        label: "시스템 스케줄러",
        path: adminRoutes.scheduler,
        icon: <ControlOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
      {
        key: "recovery",
        label: "장애 복구",
        path: adminRoutes.recovery,
        icon: <ToolOutlined />,
        enabled: true,
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

  const pathScore = (path: string): number | null => {
    if (pathname === path) return path.length;
    // /admin/ai 단독 leaf만 정확 매칭 (providers 등과 구분)
    if (path === "/admin/ai") return null;
    if (pathname.startsWith(`${path}/`)) return path.length;
    return null;
  };

  let bestPerm: string | undefined;
  let bestLen = -1;
  for (const item of flat) {
    const candidates = [
      ...(item.path ? [item.path] : []),
      ...((item.matchPaths as readonly string[] | undefined) ?? []),
    ];
    for (const path of candidates) {
      const score = pathScore(path);
      if (score != null && score > bestLen && item.permission) {
        bestLen = score;
        bestPerm = item.permission;
      }
    }
  }
  return bestPerm;
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
        // M7-A: 메뉴는 canonical /user/ai 직접 진입. /user/candidates/llm redirect page는 북마크 호환용으로 유지.
        key: "candidates-llm",
        label: "LLM 분석",
        path: userRoutes.ai,
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
        // M3-B: HIDDEN ACTIVE 승격. User owner scope, 기존 minAccess=user.
        key: "strategy-requests",
        label: "전략 요청",
        path: userRoutes.strategyRequests,
        icon: <FileSearchOutlined />,
        enabled: true,
        minAccess: "user",
      },
      {
        // M3-B: HIDDEN ACTIVE 승격. User owner scope, 기존 minAccess=user.
        key: "strategy-drafts",
        label: "전략 초안",
        path: userRoutes.strategyDrafts,
        icon: <FileTextOutlined />,
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
