import { create } from "zustand";

import type { AuthUser } from "@/features/auth/types/auth";
import { clearToken, getToken, setToken } from "@/lib/storage/tokenStorage";

interface AuthState {
  accessToken: string | null;
  user: AuthUser | null;
  authenticated: boolean;
  hydrated: boolean;
  setSession: (token: string, user: AuthUser) => void;
  clearSession: () => void;
  hydrateFromStorage: () => void;
}

const DEV_USER_STORAGE_KEY = "kiki-admin-user";

function readStoredUser(): AuthUser | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.sessionStorage.getItem(DEV_USER_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

function writeStoredUser(user: AuthUser | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!user) {
    window.sessionStorage.removeItem(DEV_USER_STORAGE_KEY);
    return;
  }
  window.sessionStorage.setItem(DEV_USER_STORAGE_KEY, JSON.stringify(user));
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  authenticated: false,
  hydrated: false,
  setSession: (token, user) => {
    setToken(token);
    writeStoredUser(user);
    set({
      accessToken: token,
      user,
      authenticated: true,
      hydrated: true,
    });
  },
  clearSession: () => {
    clearToken();
    writeStoredUser(null);
    set({
      accessToken: null,
      user: null,
      authenticated: false,
      hydrated: true,
    });
  },
  hydrateFromStorage: () => {
    const token = getToken();
    const user = readStoredUser();
    if (token && user) {
      set({
        accessToken: token,
        user,
        authenticated: true,
        hydrated: true,
      });
      return;
    }
    set({
      accessToken: null,
      user: null,
      authenticated: false,
      hydrated: true,
    });
  },
}));
