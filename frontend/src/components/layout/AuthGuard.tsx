"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { AppLoading } from "@/components/common/AppLoading";
import { routes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";

interface AuthGuardProps {
  children: React.ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { authenticated, hydrated, hydrateFromStorage } = useAuth();

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    if (!authenticated) {
      router.replace(`${routes.login}?next=${encodeURIComponent(pathname)}`);
    }
  }, [authenticated, hydrated, pathname, router]);

  if (!hydrated) {
    return <AppLoading fullScreen tip="세션 확인 중..." />;
  }

  if (!authenticated) {
    return <AppLoading fullScreen tip="로그인 페이지로 이동 중..." />;
  }

  return <>{children}</>;
}
