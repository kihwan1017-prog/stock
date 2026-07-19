"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";

import { routes } from "@/config/routes";
import { enterDevSession, loginWithCredentials, logoutRemote } from "@/features/auth/api/authApi";
import { useAuthStore } from "@/features/auth/store/authStore";
import type { LoginRequest } from "@/features/auth/types/auth";

export function useAuth() {
  const router = useRouter();
  const accessToken = useAuthStore((state) => state.accessToken);
  const user = useAuthStore((state) => state.user);
  const authenticated = useAuthStore((state) => state.authenticated);
  const hydrated = useAuthStore((state) => state.hydrated);
  const setSession = useAuthStore((state) => state.setSession);
  const clearSession = useAuthStore((state) => state.clearSession);
  const hydrateFromStorage = useAuthStore((state) => state.hydrateFromStorage);

  const login = useCallback(
    async (payload: LoginRequest) => {
      const response = await loginWithCredentials(payload);
      setSession(response.accessToken, response.user);
      router.replace(routes.dashboard);
    },
    [router, setSession],
  );

  const enterAsDev = useCallback(async () => {
    const response = await enterDevSession();
    setSession(response.accessToken, response.user);
    router.replace(routes.dashboard);
  }, [router, setSession]);

  const logout = useCallback(async () => {
    await logoutRemote();
    clearSession();
    router.replace(routes.login);
  }, [clearSession, router]);

  return {
    accessToken,
    user,
    authenticated,
    hydrated,
    login,
    enterAsDev,
    logout,
    hydrateFromStorage,
  };
}
