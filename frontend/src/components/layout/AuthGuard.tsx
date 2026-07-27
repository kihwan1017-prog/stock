"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Result } from "antd";

import { AppLoading } from "@/components/common/AppLoading";
import { permissionForPath } from "@/config/menu";
import { authRoutes, userRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import {
  hasAnyRole,
  hasPermission,
} from "@/features/auth/utils/permissions";
import { hasValidAppRole } from "@/features/auth/utils/roles";

interface AuthGuardProps {
  children: React.ReactNode;
  /** 지정 시 해당 role 중 하나 필요 */
  requiredRoles?: string[];
  /** 명시적 permission (없으면 경로 기반 menu permission 검사) */
  requiredPermissions?: string[];
  /** 경로 기반 menu permission 자동 검사 (Admin 전용) */
  enforceMenuPermission?: boolean;
  /**
   * 로그인됐지만 역할 부족일 때 이동 경로.
   * 미지정 시 /forbidden
   */
  forbiddenRedirect?: string;
}

export function AuthGuard({
  children,
  requiredRoles,
  requiredPermissions,
  enforceMenuPermission = false,
  forbiddenRedirect,
}: AuthGuardProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { authenticated, hydrated, hydrateFromStorage, user } = useAuth();

  const menuPermission = enforceMenuPermission
    ? permissionForPath(pathname)
    : undefined;
  const effectivePermissions =
    requiredPermissions ??
    (menuPermission ? [menuPermission] : undefined);

  const lacksRole = Boolean(
    requiredRoles?.length && !hasAnyRole(user, ...requiredRoles),
  );

  /** Role이 없거나 admin/user가 아니면 접근 차단 */
  const lacksValidAppRole = Boolean(
    authenticated && user && !hasValidAppRole(user.roles),
  );

  const roleFallback = forbiddenRedirect ?? authRoutes.forbidden;

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    if (!authenticated) {
      router.replace(
        `${authRoutes.login}?next=${encodeURIComponent(pathname)}`,
      );
      return;
    }
    if (lacksValidAppRole) {
      router.replace(authRoutes.forbidden);
      return;
    }
    if (lacksRole) {
      router.replace(roleFallback);
    }
  }, [
    authenticated,
    hydrated,
    pathname,
    lacksRole,
    lacksValidAppRole,
    roleFallback,
    router,
  ]);

  if (!hydrated) {
    return <AppLoading fullScreen tip="세션 확인 중..." />;
  }

  if (!authenticated) {
    return <AppLoading fullScreen tip="로그인 페이지로 이동 중..." />;
  }

  if (lacksValidAppRole) {
    return (
      <Result
        status="403"
        title="유효한 권한이 없습니다"
        subTitle="ADMIN 또는 USER 역할이 필요합니다."
        extra={
          <Button type="primary" href={authRoutes.login}>
            로그인
          </Button>
        }
      />
    );
  }

  if (lacksRole) {
    return (
      <Result
        status="403"
        title="역할 권한이 없습니다"
        subTitle={`필요 역할: ${(requiredRoles ?? []).join(", ")} · 현재: ${(user?.roles ?? []).join(", ") || "없음"}`}
        extra={
          <Button type="primary" href={roleFallback}>
            허용된 화면으로 이동
          </Button>
        }
      />
    );
  }

  if (
    effectivePermissions?.length &&
    !hasPermission(user, ...effectivePermissions)
  ) {
    return (
      <Result
        status="403"
        title="접근 권한이 없습니다"
        subTitle={`필요 권한: ${effectivePermissions.join(", ")}`}
        extra={
          <Button type="primary" href={userRoutes.dashboard}>
            사용자 대시보드
          </Button>
        }
      />
    );
  }

  return <>{children}</>;
}
