"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
import {
  SPLASH_MAX_DURATION_MS,
  logMobileBoot,
} from "@/features/mobile/mobileBootRecovery";

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
  const [bootTimedOut, setBootTimedOut] = useState(false);

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
  // 동일 경로로 replace가 반복되면 로그인↔가드 바운스를 1회로 제한
  const redirectKeyRef = useRef<string | null>(null);

  // paint 전에 sessionStorage hydrate — "세션 확인 중" 깜빡임·리다이렉트 레이스 완화
  useLayoutEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  // 부트 완료 마커 — 무한 PWA splash/timeout 가드가 정상 경로를 오판하지 않게
  useEffect(() => {
    if (!hydrated) {
      return;
    }
    document.documentElement.setAttribute("data-mobile-boot-ready", "1");
    logMobileBoot(
      authenticated ? "MOBILE_BOOT_AUTH_CHECK" : "MOBILE_BOOT_AUTH_REQUIRED",
      { path: pathname },
    );
  }, [authenticated, hydrated, pathname]);

  // 무한 splash 금지 — hydrate/redirect가 멈추면 하드 네비게이션
  useEffect(() => {
    if (hydrated && authenticated) {
      setBootTimedOut(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setBootTimedOut(true);
      logMobileBoot("MOBILE_BOOT_TIMEOUT", {
        path: pathname,
        hydrated,
        authenticated,
      });
      if (!hydrated) {
        hydrateFromStorage();
      }
      if (!authenticated) {
        const target = `${authRoutes.login}?next=${encodeURIComponent(pathname)}`;
        window.location.replace(target);
      }
    }, SPLASH_MAX_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [authenticated, hydrated, hydrateFromStorage, pathname]);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    if (!authenticated) {
      const target = `${authRoutes.login}?next=${encodeURIComponent(pathname)}`;
      if (redirectKeyRef.current === target) {
        return;
      }
      redirectKeyRef.current = target;
      router.replace(target);
      return;
    }
    if (lacksValidAppRole) {
      if (redirectKeyRef.current === authRoutes.forbidden) {
        return;
      }
      redirectKeyRef.current = authRoutes.forbidden;
      router.replace(authRoutes.forbidden);
      return;
    }
    if (lacksRole) {
      if (redirectKeyRef.current === roleFallback) {
        return;
      }
      redirectKeyRef.current = roleFallback;
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
    return (
      <AppLoading
        fullScreen
        tip={
          bootTimedOut
            ? "세션 확인이 지연되고 있습니다…"
            : "세션 확인 중..."
        }
      />
    );
  }

  if (!authenticated) {
    return (
      <AppLoading
        fullScreen
        tip={
          bootTimedOut
            ? "로그인 화면으로 이동하지 못해 다시 시도합니다…"
            : "로그인 페이지로 이동 중..."
        }
      />
    );
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
