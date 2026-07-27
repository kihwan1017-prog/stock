"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";

import { AppLoading } from "@/components/common/AppLoading";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { MainLayout } from "@/components/layout/MainLayout";
import { filterUserMenuByRoles, userMenuItems } from "@/config/menu";
import { adminRoutes, userRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { isAdminRole, requiredRolesForUserPath } from "@/features/auth/utils/roles";

export default function UserLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, authenticated, hydrated } = useAuth();

  const menuItems = useMemo(
    () => filterUserMenuByRoles(userMenuItems, user?.roles ?? []),
    [user?.roles],
  );

  const requiredRoles = requiredRolesForUserPath(pathname);

  /** STEP5: ADMIN 계정은 User 화면 대신 Admin 콘솔로 이동 (역할별 화면 분리) */
  const isAdminOnly = hydrated && authenticated && isAdminRole(user?.roles);

  useEffect(() => {
    if (isAdminOnly) {
      router.replace(adminRoutes.dashboard);
    }
  }, [isAdminOnly, router]);

  if (isAdminOnly) {
    return <AppLoading fullScreen tip="Admin 콘솔로 이동 중..." />;
  }

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
