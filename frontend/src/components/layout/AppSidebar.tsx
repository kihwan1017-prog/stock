"use client";

import { Layout, Typography } from "antd";
import type { ReactNode } from "react";

import { SidebarMenu } from "@/components/layout/SidebarMenu";
import type { AppMenuItem } from "@/config/menu";
import { adminMenuItems } from "@/config/menu";
import { env } from "@/config/env";
import { useLayoutStore } from "@/stores/layoutStore";

const { Sider } = Layout;

interface AppSidebarProps {
  collapsed?: boolean;
  menuItems?: AppMenuItem[];
  brandLabel?: string;
  footerLabel?: string;
}

export function AppSidebar({
  collapsed,
  menuItems = adminMenuItems,
  brandLabel = env.APP_NAME,
  footerLabel = "STEP41 · Admin",
}: AppSidebarProps) {
  const sidebarCollapsed = useLayoutStore((state) => state.sidebarCollapsed);
  const isCollapsed = collapsed ?? sidebarCollapsed;

  return (
    <Sider
      collapsible
      collapsed={isCollapsed}
      trigger={null}
      width={240}
      collapsedWidth={72}
      style={{
        height: "100vh",
        position: "sticky",
        top: 0,
        borderRight: "1px solid var(--app-border)",
      }}
      className="app-sidebar"
    >
      <div
        style={{
          height: 64,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: isCollapsed ? "center" : "flex-start",
          paddingInline: isCollapsed ? 0 : 16,
          borderBottom: "1px solid var(--app-border)",
        }}
      >
        <Typography.Text
          strong
          style={{
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {isCollapsed ? brandLabel.slice(0, 1).toUpperCase() : brandLabel}
        </Typography.Text>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        <SidebarMenu items={menuItems} />
      </div>

      <div
        style={{
          flexShrink: 0,
          padding: "10px 8px 14px",
          textAlign: "center",
          opacity: 0.65,
          fontSize: 12,
          lineHeight: 1.3,
          borderTop: "1px solid var(--app-border)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {isCollapsed ? "v0.1" : footerLabel}
      </div>
    </Sider>
  );
}

export type { ReactNode };
