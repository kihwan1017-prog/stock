"use client";

import { useQuery } from "@tanstack/react-query";
import { Drawer, Grid, Layout } from "antd";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/layout/AppHeader";
import { AppSidebar } from "@/components/layout/AppSidebar";
import { SidebarMenu } from "@/components/layout/SidebarMenu";
import type { AppMenuItem } from "@/config/menu";
import { adminMenuItems } from "@/config/menu";
import type { HealthResponse } from "@/lib/api/apiTypes";
import { rootClient } from "@/lib/api/rootClient";
import { queryKeys } from "@/lib/query/queryKeys";
import { useLayoutStore } from "@/stores/layoutStore";

const { Content } = Layout;
const { useBreakpoint } = Grid;

interface MainLayoutProps {
  children: ReactNode;
  menuItems?: AppMenuItem[];
  brandLabel?: string;
  footerLabel?: string;
  tradingLabel?: string;
}

async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await rootClient.get<HealthResponse>("/health");
  return data;
}

export function MainLayout({
  children,
  menuItems = adminMenuItems,
  brandLabel,
  footerLabel,
  tradingLabel = "자동매매: Placeholder",
}: MainLayoutProps) {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const mobileMenuOpen = useLayoutStore((state) => state.mobileMenuOpen);
  const setMobileMenuOpen = useLayoutStore((state) => state.setMobileMenuOpen);
  const sidebarCollapsed = useLayoutStore((state) => state.sidebarCollapsed);

  const healthQuery = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: fetchHealth,
    retry: 1,
  });

  const apiConnected = healthQuery.isSuccess
    ? true
    : healthQuery.isError
      ? false
      : null;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      {!isMobile ? (
        <AppSidebar
          collapsed={sidebarCollapsed}
          menuItems={menuItems}
          brandLabel={brandLabel}
          footerLabel={footerLabel}
        />
      ) : null}

      <Layout>
        <AppHeader apiConnected={apiConnected} tradingLabel={tradingLabel} />
        <Content style={{ margin: 0 }}>
          {children}
        </Content>
      </Layout>

      <Drawer
        title={brandLabel ?? "Menu"}
        placement="left"
        open={isMobile && mobileMenuOpen}
        onClose={() => setMobileMenuOpen(false)}
        size={280}
        styles={{ body: { padding: 0 } }}
      >
        <SidebarMenu items={menuItems} />
      </Drawer>
    </Layout>
  );
}
