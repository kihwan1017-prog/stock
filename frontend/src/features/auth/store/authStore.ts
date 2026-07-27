import { create } from "zustand";

import type { AuthUser } from "@/features/auth/types/auth";
import {
  clearRefreshToken,
  clearToken,
  getRefreshToken,
  getToken,
  isRememberMeEnabled,
  setRefreshToken,
  setToken,
} from "@/lib/storage/tokenStorage";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: AuthUser | null;
  authenticated: boolean;
  hydrated: boolean;
  setSession: (
    accessToken: string,
    user: AuthUser,
    refreshToken?: string,
    rememberMe?: boolean,
  ) => void;
  clearSession: () => void;
  hydrateFromStorage: () => void;
}

const USER_STORAGE_KEY = "kiki-admin-user";

function readStoredUser(): AuthUser | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw =
    window.localStorage.getItem(USER_STORAGE_KEY) ??
    window.sessionStorage.getItem(USER_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as AuthUser;
    return {
      ...parsed,
      roles: parsed.roles ?? [],
      permissions: parsed.permissions ?? [],
    };
  } catch {
    return null;
  }
}

function writeStoredUser(user: AuthUser | null, persist: boolean): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(USER_STORAGE_KEY);
  window.sessionStorage.removeItem(USER_STORAGE_KEY);
  if (!user) {
    return;
  }
  const store = persist ? window.localStorage : window.sessionStorage;
  store.setItem(USER_STORAGE_KEY, JSON.stringify(user));
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  refreshToken: null,
  user: null,
  authenticated: false,
  hydrated: false,
  setSession: (accessToken, user, refreshToken, rememberMe) => {
    // 토큰은 항상 sessionStorage. 사용자 프로필만 rememberMe에 따라 저장소 선택.
    const persistUser = rememberMe ?? isRememberMeEnabled();
    setToken(accessToken);
    if (refreshToken) {
      setRefreshToken(refreshToken);
    }
    writeStoredUser(user, persistUser);
    set({
      accessToken,
      refreshToken: refreshToken ?? getRefreshToken(),
      user,
      authenticated: true,
      hydrated: true,
    });
  },
  clearSession: () => {
    clearToken();
    clearRefreshToken();
    writeStoredUser(null, false);
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      authenticated: false,
      hydrated: true,
    });
  },
  hydrateFromStorage: () => {
    const token = getToken();
    const refresh = getRefreshToken();
    const user = readStoredUser();
    if (token && user) {
      set({
        accessToken: token,
        refreshToken: refresh,
        user,
        authenticated: true,
        hydrated: true,
      });
      return;
    }
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      authenticated: false,
      hydrated: true,
    });
  },
}));
