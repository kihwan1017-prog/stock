const TOKEN_STORAGE_KEY = "kiki-admin-token";
const REFRESH_STORAGE_KEY = "kiki-admin-refresh";
const PERSIST_FLAG_KEY = "kiki-admin-persist";

type StorageKind = "session" | "local";

function canUseBrowserStorage(): boolean {
  return typeof window !== "undefined";
}

function activeStorage(): Storage | null {
  if (!canUseBrowserStorage()) {
    return null;
  }
  const persist = window.localStorage.getItem(PERSIST_FLAG_KEY) === "1";
  return persist ? window.localStorage : window.sessionStorage;
}

function readFromBoth(key: string): string | null {
  if (!canUseBrowserStorage()) {
    return null;
  }
  return (
    window.localStorage.getItem(key) ?? window.sessionStorage.getItem(key)
  );
}

function writeToken(key: string, value: string, persist: boolean): void {
  if (!canUseBrowserStorage()) {
    return;
  }
  window.localStorage.removeItem(key);
  window.sessionStorage.removeItem(key);
  const store = persist ? window.localStorage : window.sessionStorage;
  store.setItem(key, value);
  if (persist) {
    window.localStorage.setItem(PERSIST_FLAG_KEY, "1");
  } else {
    window.localStorage.removeItem(PERSIST_FLAG_KEY);
  }
}

function clearBoth(key: string): void {
  if (!canUseBrowserStorage()) {
    return;
  }
  window.localStorage.removeItem(key);
  window.sessionStorage.removeItem(key);
}

export function isRememberMeEnabled(): boolean {
  if (!canUseBrowserStorage()) {
    return false;
  }
  return window.localStorage.getItem(PERSIST_FLAG_KEY) === "1";
}

export function getToken(): string | null {
  return readFromBoth(TOKEN_STORAGE_KEY);
}

export function setToken(token: string, persist = isRememberMeEnabled()): void {
  writeToken(TOKEN_STORAGE_KEY, token, persist);
}

export function clearToken(): void {
  clearBoth(TOKEN_STORAGE_KEY);
}

export function getRefreshToken(): string | null {
  return readFromBoth(REFRESH_STORAGE_KEY);
}

export function setRefreshToken(
  token: string,
  persist = isRememberMeEnabled(),
): void {
  writeToken(REFRESH_STORAGE_KEY, token, persist);
}

export function clearRefreshToken(): void {
  clearBoth(REFRESH_STORAGE_KEY);
  if (canUseBrowserStorage()) {
    window.localStorage.removeItem(PERSIST_FLAG_KEY);
  }
}

export function setRememberMe(persist: boolean): void {
  if (!canUseBrowserStorage()) {
    return;
  }
  const access = getToken();
  const refresh = getRefreshToken();
  if (persist) {
    window.localStorage.setItem(PERSIST_FLAG_KEY, "1");
  } else {
    window.localStorage.removeItem(PERSIST_FLAG_KEY);
  }
  if (access) {
    writeToken(TOKEN_STORAGE_KEY, access, persist);
  }
  if (refresh) {
    writeToken(REFRESH_STORAGE_KEY, refresh, persist);
  }
}

export const tokenStorageKey = TOKEN_STORAGE_KEY;
export const refreshTokenStorageKey = REFRESH_STORAGE_KEY;
