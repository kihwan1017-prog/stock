"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { AppLoading } from "@/components/common/AppLoading";
import { adminRoutes, authRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { canAccessAdminPortal } from "@/features/auth/utils/roles";

/**
 * USER portal 폐지 — Single Admin Operator는 Admin 콘솔만 사용.
 * 비관리자는 forbidden.
 */
export default function UserLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { user, authenticated, hydrated } = useAuth();

  useEffect(() => {
    if (!hydrated) return;
    if (!authenticated) {
      router.replace(authRoutes.login);
      return;
    }
    if (canAccessAdminPortal(user?.roles)) {
      router.replace(adminRoutes.dashboard);
      return;
    }
    router.replace(authRoutes.forbidden);
  }, [hydrated, authenticated, user?.roles, router]);

  void children;
  return <AppLoading fullScreen tip="운영 콘솔로 이동 중..." />;
}
