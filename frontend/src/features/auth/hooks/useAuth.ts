"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";

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
    async (payload: LoginRequest, redirectTo = "/user/dashboard") => {
      const response = await loginWithCredentials(payload);
      setSession(response.accessToken, response.user);
      router.replace(redirectTo);
    },
    [router, setSession],
  );

  const enterAsDev = useCallback(
    async (portal: "user" | "admin" = "admin", redirectTo?: string) => {
      const response = await enterDevSession(portal);
      setSession(response.accessToken, response.user);
      const target =
        redirectTo ?? (portal === "user" ? "/user/dashboard" : "/admin/dashboard");
      router.replace(target);
    },
    [router, setSession],
  );

  const logout = useCallback(async () => {
    await logoutRemote();
    clearSession();
    router.replace("/login");
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
