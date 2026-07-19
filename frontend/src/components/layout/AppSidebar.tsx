"use client";

import { Layout, Typography } from "antd";

import { SidebarMenu } from "@/components/layout/SidebarMenu";
import { env } from "@/config/env";
import { useLayoutStore } from "@/stores/layoutStore";

const { Sider } = Layout;

interface AppSidebarProps {
  collapsed?: boolean;
}

export function AppSidebar({ collapsed }: AppSidebarProps) {
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
        overflow: "auto",
        height: "100%",
        borderRight: "1px solid var(--app-border)",
      }}
    >
      <div
        style={{
          height: 64,
          display: "flex",
          alignItems: "center",
          justifyContent: isCollapsed ? "center" : "flex-start",
          paddingInline: isCollapsed ? 0 : 16,
          borderBottom: "1px solid var(--app-border)",
        }}
      >
        <Typography.Text strong style={{ whiteSpace: "nowrap" }}>
          {isCollapsed ? "K" : env.APP_NAME}
        </Typography.Text>
      </div>
      <SidebarMenu />
      <div
        style={{
          position: "absolute",
          bottom: 12,
          left: 0,
          right: 0,
          textAlign: "center",
          opacity: 0.65,
          fontSize: 12,
        }}
      >
        {isCollapsed ? "v0.1" : "STEP41 · v0.1.0"}
      </div>
    </Sider>
  );
}
