"use client";

import { useCallback } from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  loginWithCredentials,
  logoutRemote,
  persistRefreshToken,
  signupWithCredentials,
} from "@/features/auth/api/authApi";
import { useAuthStore } from "@/features/auth/store/authStore";
import type { LoginRequest, SignupRequest } from "@/features/auth/types/auth";
import { resolvePostLoginPath } from "@/features/auth/utils/roles";
import { authRoutes, userRoutes } from "@/config/routes";

export function useAuth() {
  const router = useRouter();
  const pathname = usePathname();
  const accessToken = useAuthStore((state) => state.accessToken);
  const user = useAuthStore((state) => state.user);
  const authenticated = useAuthStore((state) => state.authenticated);
  const hydrated = useAuthStore((state) => state.hydrated);
  const setSession = useAuthStore((state) => state.setSession);
  const clearSession = useAuthStore((state) => state.clearSession);
  const hydrateFromStorage = useAuthStore((state) => state.hydrateFromStorage);

  const login = useCallback(
    async (payload: LoginRequest, redirectTo?: string) => {
      const response = await loginWithCredentials(payload);
      setSession(
        response.accessToken,
        response.user,
        response.refreshToken,
        payload.rememberMe ?? false,
      );
      persistRefreshToken(response.refreshToken);
      const destination = resolvePostLoginPath(
        response.user,
        redirectTo ?? null,
      );
      router.replace(destination);
    },
    [router, setSession],
  );

  const signup = useCallback(
    async (payload: SignupRequest, redirectTo = userRoutes.dashboard) => {
      const response = await signupWithCredentials(payload);
      setSession(
        response.accessToken,
        response.user,
        response.refreshToken,
        true,
      );
      persistRefreshToken(response.refreshToken);
      router.replace(resolvePostLoginPath(response.user, redirectTo));
    },
    [router, setSession],
  );

  const logout = useCallback(async () => {
    const portal = pathname?.startsWith("/user") ? "user" : "admin";
    try {
      await logoutRemote();
    } finally {
      clearSession();
      router.replace(`${authRoutes.login}?portal=${portal}`);
    }
  }, [clearSession, pathname, router]);

  return {
    accessToken,
    user,
    authenticated,
    hydrated,
    login,
    signup,
    logout,
    hydrateFromStorage,
  };
}
