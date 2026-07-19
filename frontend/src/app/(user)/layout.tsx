"use client";

import type { ReactNode } from "react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { MainLayout } from "@/components/layout/MainLayout";
import { userMenuItems } from "@/config/menu";

export default function UserLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <MainLayout
        menuItems={userMenuItems}
        brandLabel="KIKI Trade"
        footerLabel="User Web · v0.1"
        tradingLabel="자동매매 상태: API 연동"
      >
        {children}
      </MainLayout>
    </AuthGuard>
  );
}
