"use client";

import type { ReactNode } from "react";
import { useMemo } from "react";
import { usePathname } from "next/navigation";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { MainLayout } from "@/components/layout/MainLayout";
import { filterUserMenuByRoles, userMenuItems } from "@/config/menu";
import { userRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { requiredRolesForUserPath } from "@/features/auth/utils/roles";

export default function UserLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();

  const menuItems = useMemo(
    () => filterUserMenuByRoles(userMenuItems, user?.roles ?? []),
    [user?.roles],
  );

  const requiredRoles = requiredRolesForUserPath(pathname);

  return (
    <AuthGuard
      requiredRoles={requiredRoles}
      forbiddenRedirect={userRoutes.dashboard}
    >
      <MainLayout
        menuItems={menuItems}
        brandLabel="KIKI Trade"
        footerLabel="User Web · v0.1"
        tradingLabel="자동매매 상태: API 연동"
      >
        {children}
      </MainLayout>
    </AuthGuard>
  );
}
