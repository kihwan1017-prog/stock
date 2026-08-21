"use client";

import type { ReactNode } from "react";
import {
  ApartmentOutlined,
  ApiOutlined,
  BarChartOutlined,
  BellOutlined,
  CloudServerOutlined,
  ControlOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FundOutlined,
  LineChartOutlined,
  MonitorOutlined,
  ReadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  ToolOutlined,
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
 * Admin 사이드바 — Single Admin Operator 콘솔.
 * 회원/권한/내정보/USER 분기 제거. WRITE는 Broker Workspace·리스크·계좌에만.
 */
export const adminMenuItems: AdminMenuItem[] = [
  {
    key: "dashboard",
    label: "대시보드",
    path: adminRoutes.dashboard,
    icon: <DashboardOutlined />,
    enabled: true,
    permission: "menu:dashboard",
  },
  {
    key: "accounts-assets",
    label: "계좌·자산",
    icon: <WalletOutlined />,
    enabled: true,
    children: [
      {
        key: "accounts",
        label: "계좌 현황",
        path: adminRoutes.accounts,
        icon: <WalletOutlined />,
        enabled: true,
        permission: "menu:accounts",
        matchPaths: [
          adminRoutes.accounts,
          adminRoutes.kiwoom,
          adminRoutes.upbit,
        ],
      },
      {
        key: "portfolio",
        label: "보유자산·손익",
        path: adminRoutes.portfolio,
        icon: <FundOutlined />,
        enabled: true,
        permission: "menu:portfolio",
      },
    ],
  },
  {
    key: "autotrading",
    label: "자동매매",
    icon: <ThunderboltOutlined />,
    enabled: true,
    children: [
      {
        key: "autotrading-kiwoom",
        label: "키움 자동매매",
        path: adminRoutes.autotradingKiwoom,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:kiwoom",
        matchPaths: [adminRoutes.autotradingKiwoom, adminRoutes.trading],
      },
      {
        key: "autotrading-upbit",
        label: "업비트 자동매매",
        path: adminRoutes.autotradingUpbit,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:upbit",
        matchPaths: [
          adminRoutes.autotradingUpbit,
          adminRoutes.upbitAutotrading,
          adminRoutes.operationsPreflight,
          adminRoutes.operationsDashboard,
        ],
      },
      {
        key: "orders",
        label: "주문·체결",
        path: adminRoutes.orders,
        icon: <ApartmentOutlined />,
        enabled: true,
        permission: "menu:orders",
        matchPaths: [adminRoutes.orders, adminRoutes.trades],
      },
    ],
  },
  {
    key: "strategy-analysis",
    label: "전략·분석",
    icon: <ExperimentOutlined />,
    enabled: true,
    children: [
      {
        key: "strategies",
        label: "전략·후보",
        path: adminRoutes.strategies,
        icon: <ExperimentOutlined />,
        enabled: true,
        permission: "menu:strategies",
        matchPaths: [
          adminRoutes.strategies,
          adminRoutes.strategyRequests,
          adminRoutes.strategyDrafts,
          adminRoutes.ai,
          adminRoutes.aiCandidateLifecycle,
          adminRoutes.aiCandidatePromotions,
          adminRoutes.aiCandidateAssessments,
          adminRoutes.aiCandidateConsensuses,
          adminRoutes.aiCandidateRecommendationQueues,
        ],
      },
      {
        key: "market-analysis",
        label: "시장 분석",
        path: adminRoutes.upbitMarkets,
        icon: <LineChartOutlined />,
        enabled: true,
        permission: "menu:upbit",
        matchPaths: [
          adminRoutes.upbitMarkets,
          adminRoutes.indicators,
          adminRoutes.aiMarketAnalyses,
        ],
      },
      {
        key: "news-disclosures",
        label: "뉴스·공시",
        path: adminRoutes.news,
        icon: <ReadOutlined />,
        enabled: true,
        permission: "menu:news",
        matchPaths: [adminRoutes.news, adminRoutes.disclosures],
      },
      {
        key: "ai-config",
        label: "AI 설정",
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
    ],
  },
  {
    key: "risk-safety",
    label: "리스크·안전",
    icon: <SafetyCertificateOutlined />,
    enabled: true,
    children: [
      {
        key: "risk",
        label: "리스크",
        path: adminRoutes.risk,
        icon: <SafetyCertificateOutlined />,
        enabled: true,
        permission: "menu:risk",
      },
      {
        key: "live-validation-upbit",
        label: "안전 제어",
        path: adminRoutes.liveValidationUpbit,
        icon: <ThunderboltOutlined />,
        enabled: true,
        permission: "menu:risk",
        matchPaths: [
          adminRoutes.liveValidationUpbit,
          adminRoutes.operationsPreflight,
        ],
      },
      {
        key: "recovery",
        label: "장애·복구",
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
        label: "알림 센터",
        path: adminRoutes.notifications,
        icon: <BellOutlined />,
        enabled: true,
        permission: "menu:notifications",
        matchPaths: [adminRoutes.notifications, adminRoutes.telegram],
      },
    ],
  },
  {
    key: "system",
    label: "시스템",
    icon: <ControlOutlined />,
    enabled: true,
    children: [
      {
        key: "system-status",
        label: "시스템 상태",
        path: adminRoutes.monitoring,
        icon: <MonitorOutlined />,
        enabled: true,
        permission: "menu:monitoring",
        matchPaths: [adminRoutes.monitoring, adminRoutes.operations],
      },
      {
        key: "schedule-batch",
        label: "스케줄·배치",
        path: adminRoutes.scheduler,
        icon: <CloudServerOutlined />,
        enabled: true,
        permission: "menu:scheduler",
        matchPaths: [adminRoutes.scheduler, adminRoutes.batch],
      },
      {
        key: "logs-audit",
        label: "로그·감사",
        path: adminRoutes.logs,
        icon: <FileSearchOutlined />,
        enabled: true,
        permission: "menu:logs",
      },
      {
        key: "data-api",
        label: "데이터·API",
        path: adminRoutes.api,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:api",
        matchPaths: [adminRoutes.api, adminRoutes.db],
      },
      {
        key: "env-settings",
        label: "환경 설정",
        path: adminRoutes.envSettings,
        icon: <SettingOutlined />,
        enabled: true,
        permission: "menu:env_settings",
        matchPaths: [adminRoutes.envSettings, adminRoutes.systemSettings],
      },
      {
        key: "ai-infra",
        label: "AI 인프라",
        path: adminRoutes.ollama,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ollama",
      },
      {
        key: "docs",
        label: "문서",
        path: adminRoutes.docs,
        icon: <FileTextOutlined />,
        enabled: true,
        permission: "menu:docs",
        matchPaths: [adminRoutes.docs, adminRoutes.docsManual],
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
 * USER 사이드바 — Single Admin Operator 전환 후 비노출.
 * route/page는 호환용으로 유지하되 layout에서 /admin으로 redirect.
 */
export const userMenuItems: UserMenuItem[] = [];
