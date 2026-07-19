import type { AxiosInstance, InternalAxiosRequestConfig } from "axios";

import { routes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { clearToken, getToken } from "@/lib/storage/tokenStorage";
import { logger } from "@/utils/logger";

let isRedirectingToLogin = false;

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
  window.sessionStorage.removeItem("kiki-admin-user");

  // 무한 redirect 방지
  if (isRedirectingToLogin || window.location.pathname === routes.login) {
    return;
  }

  isRedirectingToLogin = true;
  window.location.assign(routes.login);
}

export function setupInterceptors(client: AxiosInstance): void {
  client.interceptors.request.use(
    (config) => attachAuthHeader(config),
    (error: unknown) => Promise.reject(toApiError(error)),
  );

  client.interceptors.response.use(
    (response) => response,
    (error: unknown) => {
      const apiError = toApiError(error);
      logger.warn("API request failed", {
        status: apiError.status,
        code: apiError.code,
        message: apiError.message,
        requestId: apiError.requestId,
      });

      if (apiError.status === 401) {
        handleUnauthorized();
      }

      return Promise.reject(apiError);
    },
  );
}
