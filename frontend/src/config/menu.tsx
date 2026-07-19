"use client";

import type { ReactNode } from "react";
import {
  ApiOutlined,
  ApartmentOutlined,
  BarChartOutlined,
  BellOutlined,
  CloudServerOutlined,
  ControlOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FundOutlined,
  KeyOutlined,
  MonitorOutlined,
  ReadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  SwapOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
  WalletOutlined,
} from "@ant-design/icons";

import { adminRoutes, userRoutes } from "@/config/routes";
import { meetsUserMenuAccess } from "@/features/auth/utils/roles";

export interface AppMenuItem {
  key: string;
  label: string;
  path?: string;
  icon?: ReactNode;
  enabled: boolean;
  /** 메뉴 표시에 필요한 permission (없으면 로그인만) */
  permission?: string;
  /**
   * User 메뉴 최소 역할 티어 (viewer 기본).
   * trader = Backend operator | trader | admin
   */
  minAccess?: "viewer" | "trader" | "admin";
  children?: AppMenuItem[];
}

export const adminMenuItems: AppMenuItem[] = [
  {
    key: "overview",
    label: "개요",
    icon: <DashboardOutlined />,
    enabled: true,
    children: [
      {
        key: "dashboard",
        label: "Dashboard",
        path: adminRoutes.dashboard,
        icon: <DashboardOutlined />,
        enabled: true,
        permission: "menu:dashboard",
      },
      {
        key: "monitoring",
        label: "시스템 모니터링",
        path: adminRoutes.monitoring,
        icon: <MonitorOutlined />,
        enabled: true,
        permission: "menu:monitoring",
      },
    ],
  },
  {
    key: "users",
    label: "사용자",
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
    key: "trading-group",
    label: "거래",
    icon: <SwapOutlined />,
    enabled: true,
    children: [
      {
        key: "accounts",
        label: "계좌관리",
        path: adminRoutes.accounts,
        icon: <WalletOutlined />,
        enabled: true,
        permission: "menu:accounts",
      },
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
        label: "포트폴리오",
        path: adminRoutes.portfolio,
        icon: <FundOutlined />,
        enabled: true,
        permission: "menu:portfolio",
      },
    ],
  },
  {
    key: "strategy-ai",
    label: "전략·AI",
    icon: <ExperimentOutlined />,
    enabled: true,
    children: [
      {
        key: "strategies",
        label: "전략관리",
        path: adminRoutes.strategies,
        icon: <ExperimentOutlined />,
        enabled: true,
        permission: "menu:strategies",
      },
      {
        key: "ai",
        label: "AI 관리",
        path: adminRoutes.ai,
        icon: <RobotOutlined />,
        enabled: true,
        permission: "menu:ai",
      },
      {
        key: "backtests",
        label: "백테스트",
        path: adminRoutes.backtests,
        icon: <BarChartOutlined />,
        enabled: true,
        permission: "menu:backtests",
      },
    ],
  },
  {
    key: "content",
    label: "콘텐츠",
    icon: <ReadOutlined />,
    enabled: true,
    children: [
      {
        key: "news",
        label: "뉴스관리",
        path: adminRoutes.news,
        icon: <ReadOutlined />,
        enabled: true,
        permission: "menu:news",
      },
      {
        key: "disclosures",
        label: "공시관리",
        path: adminRoutes.disclosures,
        icon: <FileTextOutlined />,
        enabled: true,
        permission: "menu:disclosures",
      },
    ],
  },
  {
    key: "ops",
    label: "리스크·운영",
    icon: <SafetyCertificateOutlined />,
    enabled: true,
    children: [
      {
        key: "operations",
        label: "운영센터",
        path: adminRoutes.operations,
        icon: <ControlOutlined />,
        enabled: true,
        permission: "menu:scheduler",
      },
      {
        key: "risk",
        label: "Risk 관리",
        path: adminRoutes.risk,
        icon: <SafetyCertificateOutlined />,
        enabled: true,
        permission: "menu:risk",
      },
      {
        key: "scheduler",
        label: "Scheduler 관리",
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
    key: "broker-data",
    label: "브로커·데이터",
    icon: <ApiOutlined />,
    enabled: true,
    children: [
      {
        key: "kiwoom",
        label: "키움 API 관리",
        path: adminRoutes.kiwoom,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:kiwoom",
      },
      {
        key: "upbit",
        label: "업비트 관리",
        path: adminRoutes.upbit,
        icon: <ApiOutlined />,
        enabled: true,
        permission: "menu:upbit",
      },
      {
        key: "data",
        label: "데이터·모니터링",
        path: adminRoutes.monitoring,
        icon: <DatabaseOutlined />,
        enabled: true,
        permission: "menu:data",
      },
    ],
  },
  {
    key: "system",
    label: "시스템",
    icon: <SettingOutlined />,
    enabled: true,
    children: [
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
        key: "docs",
        label: "문서 관리",
        path: adminRoutes.docs,
        icon: <FileTextOutlined />,
        enabled: true,
        permission: "menu:docs",
      },
    ],
  },
];

/** @deprecated adminMenuItems 사용 */
export const appMenuItems = adminMenuItems;

/** 플랫 메뉴 경로 목록 (가드·테스트용) */
export function flattenMenuItems(items: AppMenuItem[]): AppMenuItem[] {
  const result: AppMenuItem[] = [];
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
export function filterMenuByPermissions(
  items: AppMenuItem[],
  permissions: string[],
  roles: string[] = [],
): AppMenuItem[] {
  const isAdmin = roles.includes("admin");
  const owned = new Set(permissions);

  const filterNode = (item: AppMenuItem): AppMenuItem | null => {
    if (!item.enabled) {
      return null;
    }
    if (item.children?.length) {
      const children = item.children
        .map(filterNode)
        .filter((child): child is AppMenuItem => child !== null);
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
    .filter((item): item is AppMenuItem => item !== null);
}

/** User 메뉴 — 역할 티어로 필터 (viewer / trader / admin) */
export function filterUserMenuByRoles(
  items: AppMenuItem[],
  roles: string[],
): AppMenuItem[] {
  const filterNode = (item: AppMenuItem): AppMenuItem | null => {
    if (!item.enabled) return null;
    if (item.children?.length) {
      const children = item.children
        .map(filterNode)
        .filter((child): child is AppMenuItem => child !== null);
      if (!children.length) return null;
      return { ...item, children };
    }
    const minAccess = item.minAccess ?? "viewer";
    if (!meetsUserMenuAccess(roles, minAccess)) {
      return null;
    }
    return item;
  };

  return items
    .map(filterNode)
    .filter((item): item is AppMenuItem => item !== null);
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

export const userMenuItems: AppMenuItem[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    path: userRoutes.dashboard,
    icon: <DashboardOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "account",
    label: "내 계좌",
    path: userRoutes.account,
    icon: <WalletOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "trading",
    label: "매매",
    path: userRoutes.trading,
    icon: <SwapOutlined />,
    enabled: true,
    minAccess: "trader",
  },
  {
    key: "auto-trading",
    label: "자동매매",
    path: userRoutes.autoTrading,
    icon: <ThunderboltOutlined />,
    enabled: true,
    minAccess: "trader",
  },
  {
    key: "strategies",
    label: "전략",
    path: userRoutes.strategies,
    icon: <ExperimentOutlined />,
    enabled: true,
    minAccess: "trader",
  },
  {
    key: "backtests",
    label: "백테스트",
    path: userRoutes.backtests,
    icon: <BarChartOutlined />,
    enabled: true,
    minAccess: "trader",
  },
  {
    key: "portfolio",
    label: "포트폴리오",
    path: userRoutes.portfolio,
    icon: <FundOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "trades",
    label: "거래내역",
    path: userRoutes.trades,
    icon: <ApartmentOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "ai",
    label: "AI 추천",
    path: userRoutes.ai,
    icon: <RobotOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "news",
    label: "뉴스",
    path: userRoutes.news,
    icon: <ReadOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "disclosures",
    label: "공시",
    path: userRoutes.disclosures,
    icon: <FileTextOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "notifications",
    label: "알림",
    path: userRoutes.notifications,
    icon: <BellOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "settings",
    label: "설정",
    path: userRoutes.settings,
    icon: <SettingOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
  {
    key: "profile",
    label: "내 정보",
    path: userRoutes.profile,
    icon: <UserOutlined />,
    enabled: true,
    minAccess: "viewer",
  },
];
