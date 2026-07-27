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
  // 통합 로그인: portal 쿼리 없이 /login 으로만 이동
  window.location.assign(routes.login);
}

/** 로그인·가입·토큰 갱신 등 — 401을 세션 만료로 취급하지 않음 */
function isAuthEndpoint(url?: string): boolean {
  if (!url) return false;
  return (
    url.includes("/auth/login") ||
    url.includes("/auth/signup") ||
    url.includes("/auth/refresh") ||
    url.includes("/auth/logout") ||
    url.includes("/auth/change-password")
  );
}

async function refreshAndRetry(
  client: AxiosInstance,
  original: InternalAxiosRequestConfig & { _retry?: boolean },
  apiError: ReturnType<typeof toApiError>,
): Promise<unknown> {
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
    const { refreshAccessToken } = await import("@/features/auth/api/authApi");
    const { useAuthStore } = await import("@/features/auth/store/authStore");
    const refreshed = await refreshAccessToken(refreshToken);
    setToken(refreshed.accessToken);
    setRefreshToken(refreshed.refreshToken);
    useAuthStore
      .getState()
      .setSession(refreshed.accessToken, refreshed.user, refreshed.refreshToken);
    notifyRefreshWaiters(refreshed.accessToken);
    original.headers.set("Authorization", `Bearer ${refreshed.accessToken}`);
    return client.request(original);
  } catch {
    notifyRefreshWaiters(null);
    handleUnauthorized();
    return Promise.reject(apiError);
  } finally {
    isRefreshing = false;
  }
}

export function setupInterceptors(client: AxiosInstance): void {
  client.interceptors.request.use(
    (config) => attachAuthHeader(config),
    (error: unknown) => Promise.reject(toApiError(error)),
  );

  client.interceptors.response.use(
    (response) => response,
    (error: unknown) => {
      // async 인터셉터 전체가 Promise가 되면 unhandledrejection 타이밍 이슈가 생길 수 있어
      // 일반 경로는 동기 reject, refresh 만 async로 분리
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

      const canRefresh =
        apiError.status === 401 &&
        Boolean(original) &&
        !original!._retry &&
        !isAuthEndpoint(original?.url);

      if (canRefresh && original) {
        return refreshAndRetry(client, original, apiError);
      }

      // 로그인 실패(401) 등은 세션 만료 처리하지 않음
      if (apiError.status === 401 && !isAuthEndpoint(original?.url)) {
        handleUnauthorized();
      }

      return Promise.reject(apiError);
    },
  );
}
