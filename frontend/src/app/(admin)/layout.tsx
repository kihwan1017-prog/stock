"use client";

import type { ReactNode } from "react";
import { useMemo } from "react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { MainLayout } from "@/components/layout/MainLayout";
import {
  adminMenuItems,
  filterMenuByPermissions,
} from "@/config/menu";
import { userRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { user } = useAuth();

  const menuItems = useMemo(
    () =>
      filterMenuByPermissions(
        adminMenuItems,
        user?.permissions ?? [],
        user?.roles ?? [],
      ),
    [user?.permissions, user?.roles],
  );

  return (
    <AuthGuard
      requiredRoles={["admin", "operator"]}
      enforceMenuPermission
      forbiddenRedirect={userRoutes.dashboard}
    >
      <MainLayout
        menuItems={menuItems}
        brandLabel="KIKI Admin"
        footerLabel="Admin Console"
        tradingLabel="Admin"
      >
        {children}
      </MainLayout>
    </AuthGuard>
  );
}
