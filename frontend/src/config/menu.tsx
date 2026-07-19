import type { ReactNode } from "react";
import {
  ApartmentOutlined,
  BarChartOutlined,
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
} from "@ant-design/icons";

import { routes } from "@/config/routes";

export interface AppMenuItem {
  key: string;
  label: string;
  path: string;
  icon: ReactNode;
  enabled: boolean;
}

export const appMenuItems: AppMenuItem[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    path: routes.dashboard,
    icon: <DashboardOutlined />,
    enabled: true,
  },
  {
    key: "market",
    label: "Market",
    path: routes.market,
    icon: <LineChartOutlined />,
    enabled: true,
  },
  {
    key: "ai",
    label: "AI Center",
    path: routes.ai,
    icon: <RobotOutlined />,
    enabled: true,
  },
  {
    key: "trading",
    label: "Trading",
    path: routes.trading,
    icon: <SwapOutlined />,
    enabled: true,
  },
  {
    key: "orders",
    label: "Orders",
    path: routes.orders,
    icon: <ApartmentOutlined />,
    enabled: true,
  },
  {
    key: "positions",
    label: "Positions",
    path: routes.positions,
    icon: <FundOutlined />,
    enabled: true,
  },
  {
    key: "risk",
    label: "Risk",
    path: routes.risk,
    icon: <SafetyCertificateOutlined />,
    enabled: true,
  },
  {
    key: "strategies",
    label: "Strategy",
    path: routes.strategies,
    icon: <ExperimentOutlined />,
    enabled: true,
  },
  {
    key: "news",
    label: "News",
    path: routes.news,
    icon: <ReadOutlined />,
    enabled: true,
  },
  {
    key: "disclosures",
    label: "Disclosure",
    path: routes.disclosures,
    icon: <FileTextOutlined />,
    enabled: true,
  },
  {
    key: "backtests",
    label: "Backtest",
    path: routes.backtests,
    icon: <BarChartOutlined />,
    enabled: true,
  },
  {
    key: "operations",
    label: "Operations",
    path: routes.operations,
    icon: <ControlOutlined />,
    enabled: true,
  },
  {
    key: "settings",
    label: "Settings",
    path: routes.settings,
    icon: <SettingOutlined />,
    enabled: true,
  },
];
