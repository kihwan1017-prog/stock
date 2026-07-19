"use client";

import type { ReactNode } from "react";
import {
  ApartmentOutlined,
  BarChartOutlined,
  BellOutlined,
  ControlOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  FundOutlined,
  LineChartOutlined,
  ReadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  SwapOutlined,
  UserOutlined,
  WalletOutlined,
} from "@ant-design/icons";

import { adminRoutes, userRoutes } from "@/config/routes";

export interface AppMenuItem {
  key: string;
  label: string;
  path: string;
  icon: ReactNode;
  enabled: boolean;
}

export const adminMenuItems: AppMenuItem[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    path: adminRoutes.dashboard,
    icon: <DashboardOutlined />,
    enabled: true,
  },
  {
    key: "market",
    label: "Market",
    path: adminRoutes.market,
    icon: <LineChartOutlined />,
    enabled: true,
  },
  {
    key: "ai",
    label: "AI Center",
    path: adminRoutes.ai,
    icon: <RobotOutlined />,
    enabled: true,
  },
  {
    key: "trading",
    label: "Trading",
    path: adminRoutes.trading,
    icon: <SwapOutlined />,
    enabled: true,
  },
  {
    key: "orders",
    label: "Orders",
    path: adminRoutes.orders,
    icon: <ApartmentOutlined />,
    enabled: true,
  },
  {
    key: "positions",
    label: "Positions",
    path: adminRoutes.positions,
    icon: <FundOutlined />,
    enabled: true,
  },
  {
    key: "risk",
    label: "Risk",
    path: adminRoutes.risk,
    icon: <SafetyCertificateOutlined />,
    enabled: true,
  },
  {
    key: "strategies",
    label: "Strategy",
    path: adminRoutes.strategies,
    icon: <ExperimentOutlined />,
    enabled: true,
  },
  {
    key: "news",
    label: "News",
    path: adminRoutes.news,
    icon: <ReadOutlined />,
    enabled: true,
  },
  {
    key: "disclosures",
    label: "Disclosure",
    path: adminRoutes.disclosures,
    icon: <FileTextOutlined />,
    enabled: true,
  },
  {
    key: "backtests",
    label: "Backtest",
    path: adminRoutes.backtests,
    icon: <BarChartOutlined />,
    enabled: true,
  },
  {
    key: "operations",
    label: "Operations",
    path: adminRoutes.operations,
    icon: <ControlOutlined />,
    enabled: true,
  },
  {
    key: "settings",
    label: "Settings",
    path: adminRoutes.settings,
    icon: <SettingOutlined />,
    enabled: true,
  },
];

/** @deprecated adminMenuItems 사용 */
export const appMenuItems = adminMenuItems;

export const userMenuItems: AppMenuItem[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    path: userRoutes.dashboard,
    icon: <DashboardOutlined />,
    enabled: true,
  },
  {
    key: "account",
    label: "내 계좌",
    path: userRoutes.account,
    icon: <WalletOutlined />,
    enabled: true,
  },
  {
    key: "trading",
    label: "자동매매",
    path: userRoutes.trading,
    icon: <SwapOutlined />,
    enabled: true,
  },
  {
    key: "strategies",
    label: "전략",
    path: userRoutes.strategies,
    icon: <ExperimentOutlined />,
    enabled: true,
  },
  {
    key: "backtests",
    label: "백테스트",
    path: userRoutes.backtests,
    icon: <BarChartOutlined />,
    enabled: true,
  },
  {
    key: "portfolio",
    label: "포트폴리오",
    path: userRoutes.portfolio,
    icon: <FundOutlined />,
    enabled: true,
  },
  {
    key: "trades",
    label: "거래내역",
    path: userRoutes.trades,
    icon: <ApartmentOutlined />,
    enabled: true,
  },
  {
    key: "ai",
    label: "AI 추천",
    path: userRoutes.ai,
    icon: <RobotOutlined />,
    enabled: true,
  },
  {
    key: "news",
    label: "뉴스",
    path: userRoutes.news,
    icon: <ReadOutlined />,
    enabled: true,
  },
  {
    key: "disclosures",
    label: "공시",
    path: userRoutes.disclosures,
    icon: <FileTextOutlined />,
    enabled: true,
  },
  {
    key: "notifications",
    label: "알림",
    path: userRoutes.notifications,
    icon: <BellOutlined />,
    enabled: true,
  },
  {
    key: "settings",
    label: "설정",
    path: userRoutes.settings,
    icon: <SettingOutlined />,
    enabled: true,
  },
  {
    key: "profile",
    label: "내 정보",
    path: userRoutes.profile,
    icon: <UserOutlined />,
    enabled: true,
  },
];
