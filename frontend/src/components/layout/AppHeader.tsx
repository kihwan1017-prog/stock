"use client";

import {
  DesktopOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  SunOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Dropdown, Flex, Layout, Space, Tag, Typography } from "antd";
import type { MenuProps } from "antd";
import { usePathname } from "next/navigation";

import { StatusBadge } from "@/components/common/StatusBadge";
import { env } from "@/config/env";
import { getRouteTitle } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useThemeMode } from "@/hooks/useThemeMode";
import { useLayoutStore } from "@/stores/layoutStore";

const { Header } = Layout;

interface AppHeaderProps {
  apiConnected?: boolean | null;
}

export function AppHeader({ apiConnected = null }: AppHeaderProps) {
  const pathname = usePathname();
  const title = getRouteTitle(pathname);
  const { user, logout } = useAuth();
  const { mode, setMode } = useThemeMode();
  const sidebarCollapsed = useLayoutStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useLayoutStore((state) => state.toggleSidebar);
  const setMobileMenuOpen = useLayoutStore((state) => state.setMobileMenuOpen);

  const themeItems: MenuProps["items"] = [
    { key: "light", icon: <SunOutlined />, label: "Light", onClick: () => setMode("light") },
    { key: "dark", icon: <MoonOutlined />, label: "Dark", onClick: () => setMode("dark") },
    {
      key: "system",
      icon: <DesktopOutlined />,
      label: "System",
      onClick: () => setMode("system"),
    },
  ];

  const userItems: MenuProps["items"] = [
    {
      key: "logout",
      icon: <LogoutOutlined />,
      label: "로그아웃",
      onClick: () => {
        void logout();
      },
    },
  ];

  const apiStatus =
    apiConnected === null ? "unknown" : apiConnected ? ("healthy" as const) : ("error" as const);

  return (
    <Header
      style={{
        paddingInline: 16,
        background: "transparent",
        borderBottom: "1px solid var(--app-border)",
        height: 64,
        display: "flex",
        alignItems: "center",
      }}
    >
      <Flex justify="space-between" align="center" style={{ width: "100%" }} wrap gap={12}>
        <Space>
          <Button
            type="text"
            className="desktop-only"
            icon={sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={toggleSidebar}
            aria-label="사이드바 토글"
          />
          <Button
            type="text"
            className="mobile-only"
            icon={<MenuUnfoldOutlined />}
            onClick={() => setMobileMenuOpen(true)}
            aria-label="모바일 메뉴 열기"
          />
          <Typography.Title level={4} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
        </Space>

        <Space wrap size="middle">
          <Space size={4}>
            <Typography.Text type="secondary">API</Typography.Text>
            <StatusBadge
              status={apiStatus}
              label={
                apiConnected === null ? "확인 중" : apiConnected ? "연결됨" : "연결 실패"
              }
            />
          </Space>

          <Tag color="processing">자동매매: Placeholder</Tag>

          {env.AUTH_MODE === "disabled" ? <Tag color="warning">AUTH DISABLED</Tag> : null}

          <Dropdown menu={{ items: themeItems, selectedKeys: [mode] }} placement="bottomRight">
            <Button type="text" icon={<DesktopOutlined />}>
              Theme
            </Button>
          </Dropdown>

          <Dropdown menu={{ items: userItems }} placement="bottomRight">
            <Button type="text" icon={<UserOutlined />}>
              {user?.displayName ?? user?.username ?? "Guest"}
            </Button>
          </Dropdown>
        </Space>
      </Flex>
    </Header>
  );
}
