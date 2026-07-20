"use client";

import {
  BellOutlined,
  ControlOutlined,
  DesktopOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  SettingOutlined,
  SunOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Badge, Button, Dropdown, Flex, Layout, Space, Tag, Typography } from "antd";
import type { MenuProps } from "antd";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { StatusBadge } from "@/components/common/StatusBadge";
import { adminRoutes, getRouteTitle, userRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import {
  canAccessAdminPortal,
  primaryProductRole,
} from "@/features/auth/utils/roles";
import * as userApi from "@/features/user/api/userApi";
import { useThemeMode } from "@/hooks/useThemeMode";
import { queryKeys } from "@/lib/query/queryKeys";
import { useLayoutStore } from "@/stores/layoutStore";

const { Header } = Layout;

interface AppHeaderProps {
  apiConnected?: boolean | null;
  tradingLabel?: string;
}

export function AppHeader({
  apiConnected = null,
  tradingLabel = "자동매매: Placeholder",
}: AppHeaderProps) {
  const pathname = usePathname();
  const title = getRouteTitle(pathname);
  const { user, logout } = useAuth();
  const { mode, setMode } = useThemeMode();
  const sidebarCollapsed = useLayoutStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useLayoutStore((state) => state.toggleSidebar);
  const setMobileMenuOpen = useLayoutStore((state) => state.setMobileMenuOpen);

  const isUserArea = pathname.startsWith("/user");
  const unreadQuery = useQuery({
    queryKey: queryKeys.user.notifications.unreadCount(),
    queryFn: () => userApi.getNotificationUnreadCount(),
    enabled: isUserArea && Boolean(user),
    refetchInterval: 30_000,
    retry: false,
  });

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

  const productRole = primaryProductRole(user?.roles);
  const showAdminLink = canAccessAdminPortal(user?.roles);

  const userItems: MenuProps["items"] = [
    {
      key: "profile",
      icon: <UserOutlined />,
      label: <Link href={userRoutes.profile}>My Page</Link>,
    },
    {
      key: "settings",
      icon: <SettingOutlined />,
      label: <Link href={userRoutes.settings}>설정</Link>,
    },
    ...(showAdminLink
      ? [
          {
            key: "admin",
            icon: <ControlOutlined />,
            label: <Link href={adminRoutes.dashboard}>Admin 콘솔</Link>,
          },
        ]
      : []),
    { type: "divider" as const },
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

  const roleColor =
    productRole === "admin"
      ? "red"
      : productRole === "trader"
        ? "blue"
        : "default";

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

          <Tag color="processing">{tradingLabel}</Tag>

          {user ? (
            <Tag color={roleColor}>{productRole}</Tag>
          ) : null}

          {isUserArea && user ? (
            <Link href={userRoutes.notifications} aria-label="알림 센터">
              <Badge count={unreadQuery.data?.unread_count ?? 0} size="small" overflowCount={99}>
                <Button type="text" icon={<BellOutlined />} />
              </Badge>
            </Link>
          ) : null}

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
