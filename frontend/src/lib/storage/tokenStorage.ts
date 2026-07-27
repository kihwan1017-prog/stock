const TOKEN_STORAGE_KEY = "kiki-admin-token";
const REFRESH_STORAGE_KEY = "kiki-admin-refresh";

/**
 * 증권사 납품 기준: access/refresh 토큰은 sessionStorage만 사용.
 * localStorage 영속화(Remember Me)는 XSS 지속 노출 위험이 있어 제거.
 * Next middleware 정합을 위해 동일 이름의 session 쿠키도 동기화한다.
 */

function canUseBrowserStorage(): boolean {
  return typeof window !== "undefined";
}

function syncAuthCookie(name: string, value: string | null): void {
  if (!canUseBrowserStorage()) {
    return;
  }
  if (!value) {
    document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax`;
    return;
  }
  // session cookie (Max-Age 미지정) — 탭 종료 시 브라우저가 정리
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; SameSite=Lax`;
}

function readSession(key: string): string | null {
  if (!canUseBrowserStorage()) {
    return null;
  }
  return window.sessionStorage.getItem(key);
}

function writeSession(key: string, value: string): void {
  if (!canUseBrowserStorage()) {
    return;
  }
  // 레거시 localStorage 잔여분 제거
  window.localStorage.removeItem(key);
  window.sessionStorage.setItem(key, value);
  syncAuthCookie(key, value);
}

function clearSession(key: string): void {
  if (!canUseBrowserStorage()) {
    return;
  }
  window.localStorage.removeItem(key);
  window.sessionStorage.removeItem(key);
  syncAuthCookie(key, null);
}

export function isRememberMeEnabled(): boolean {
  // 보안 정책상 Remember Me(토큰 localStorage) 비활성
  return false;
}

export function getToken(): string | null {
  return readSession(TOKEN_STORAGE_KEY);
}

/** Access Token은 항상 sessionStorage — persist 인자 없음(레거시 제거). */
export function setToken(token: string): void {
  writeSession(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  clearSession(TOKEN_STORAGE_KEY);
}

export function getRefreshToken(): string | null {
  return readSession(REFRESH_STORAGE_KEY);
}

/** Refresh Token은 항상 sessionStorage — persist 인자 없음(레거시 제거). */
export function setRefreshToken(token: string): void {
  writeSession(REFRESH_STORAGE_KEY, token);
}

export function clearRefreshToken(): void {
  clearSession(REFRESH_STORAGE_KEY);
  if (canUseBrowserStorage()) {
    window.localStorage.removeItem("kiki-admin-persist");
  }
}

export const tokenStorageKey = TOKEN_STORAGE_KEY;
export const refreshTokenStorageKey = REFRESH_STORAGE_KEY;
