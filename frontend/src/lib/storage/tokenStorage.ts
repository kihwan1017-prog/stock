const TOKEN_STORAGE_KEY = "kiki-admin-token";

function canUseSessionStorage(): boolean {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

export function getToken(): string | null {
  if (!canUseSessionStorage()) {
    return null;
  }
  return window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  if (!canUseSessionStorage()) {
    return;
  }
  window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  if (!canUseSessionStorage()) {
    return;
  }
  window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

export const tokenStorageKey = TOKEN_STORAGE_KEY;
