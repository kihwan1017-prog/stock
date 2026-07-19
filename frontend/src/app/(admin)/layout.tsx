"use client";

import type { ReactNode } from "react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { MainLayout } from "@/components/layout/MainLayout";
import { adminMenuItems } from "@/config/menu";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <MainLayout
        menuItems={adminMenuItems}
        brandLabel="KIKI Admin"
        footerLabel="STEP41 · Admin"
        tradingLabel="Admin · Placeholder"
      >
        {children}
      </MainLayout>
    </AuthGuard>
  );
}
