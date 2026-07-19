import type { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from "axios";

import { routes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import {
  clearRefreshToken,
  clearToken,
  getRefreshToken,
  getToken,
  setRefreshToken,
  setToken,
} from "@/lib/storage/tokenStorage";
import { logger } from "@/utils/logger";

let isRedirectingToLogin = false;
let isRefreshing = false;
let refreshWaiters: Array<(token: string | null) => void> = [];

function notifyRefreshWaiters(token: string | null): void {
  refreshWaiters.forEach((resolve) => resolve(token));
  refreshWaiters = [];
}

function attachAuthHeader(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const token = getToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
}

function handleUnauthorized(): void {
  if (typeof window === "undefined") {
    return;
  }

  clearToken();
  clearRefreshToken();
  window.sessionStorage.removeItem("kiki-admin-user");

  void import("@/features/auth/store/authStore").then(({ useAuthStore }) => {
    useAuthStore.getState().clearSession();
  });

  if (isRedirectingToLogin || window.location.pathname === routes.login) {
    return;
  }

  isRedirectingToLogin = true;
  window.location.assign(`${routes.login}?portal=admin`);
}

function isAuthEndpoint(url?: string): boolean {
  if (!url) return false;
  return (
    url.includes("/auth/login") ||
    url.includes("/auth/refresh") ||
    url.includes("/auth/logout")
  );
}

export function setupInterceptors(client: AxiosInstance): void {
  client.interceptors.request.use(
    (config) => attachAuthHeader(config),
    (error: unknown) => Promise.reject(toApiError(error)),
  );

  client.interceptors.response.use(
    (response) => response,
    async (error: unknown) => {
      const apiError = toApiError(error);
      const axiosError = error as AxiosError;
      const original = axiosError.config as
        | (InternalAxiosRequestConfig & { _retry?: boolean })
        | undefined;

      logger.warn("API request failed", {
        status: apiError.status,
        code: apiError.code,
        message: apiError.message,
        requestId: apiError.requestId,
      });

      if (
        apiError.status === 401 &&
        original &&
        !original._retry &&
        !isAuthEndpoint(original.url)
      ) {
        const refreshToken = getRefreshToken();
        if (!refreshToken) {
          handleUnauthorized();
          return Promise.reject(apiError);
        }

        if (isRefreshing) {
          const nextToken = await new Promise<string | null>((resolve) => {
            refreshWaiters.push(resolve);
          });
          if (!nextToken) {
            return Promise.reject(apiError);
          }
          original.headers.set("Authorization", `Bearer ${nextToken}`);
          return client.request(original);
        }

        original._retry = true;
        isRefreshing = true;
        try {
          const { refreshAccessToken } = await import(
            "@/features/auth/api/authApi"
          );
          const { useAuthStore } = await import(
            "@/features/auth/store/authStore"
          );
          const refreshed = await refreshAccessToken(refreshToken);
          setToken(refreshed.accessToken);
          setRefreshToken(refreshed.refreshToken);
          useAuthStore
            .getState()
            .setSession(
              refreshed.accessToken,
              refreshed.user,
              refreshed.refreshToken,
            );
          notifyRefreshWaiters(refreshed.accessToken);
          original.headers.set(
            "Authorization",
            `Bearer ${refreshed.accessToken}`,
          );
          return client.request(original);
        } catch {
          notifyRefreshWaiters(null);
          handleUnauthorized();
          return Promise.reject(apiError);
        } finally {
          isRefreshing = false;
        }
      }

      if (apiError.status === 401) {
        handleUnauthorized();
      }

      return Promise.reject(apiError);
    },
  );
}
