"use client";

import { useQuery } from "@tanstack/react-query";
import { Drawer, Grid, Layout } from "antd";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/layout/AppHeader";
import { AppSidebar } from "@/components/layout/AppSidebar";
import { SidebarMenu } from "@/components/layout/SidebarMenu";
import type { HealthResponse } from "@/lib/api/apiTypes";
import { rootClient } from "@/lib/api/rootClient";
import { queryKeys } from "@/lib/query/queryKeys";
import { useLayoutStore } from "@/stores/layoutStore";

const { Content } = Layout;
const { useBreakpoint } = Grid;

interface MainLayoutProps {
  children: ReactNode;
}

async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await rootClient.get<HealthResponse>("/health");
  return data;
}

export function MainLayout({ children }: MainLayoutProps) {
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
      {!isMobile ? <AppSidebar collapsed={sidebarCollapsed} /> : null}

      <Drawer
        title="메뉴"
        placement="left"
        open={isMobile && mobileMenuOpen}
        onClose={() => setMobileMenuOpen(false)}
        styles={{ body: { padding: 0 } }}
        size={260}
      >
        <SidebarMenu />
      </Drawer>

      <Layout>
        <AppHeader apiConnected={apiConnected} />
        <Content style={{ minHeight: 280 }}>{children}</Content>
      </Layout>
    </Layout>
  );
}
