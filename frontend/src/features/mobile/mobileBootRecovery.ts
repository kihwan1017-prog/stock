/**
 * 모바일/PWA 부트 복구 — 민감정보 없이 terminal transition 보장.
 * reload loop 방지: sessionStorage 1회 가드.
 */

export const SPLASH_MAX_DURATION_MS = 8_000;
export const MOBILE_BOOT_RECOVERY_KEY = "stock-mobile-boot-recovery-v1";

export type MobileBootEvent =
  | "MOBILE_BOOT_START"
  | "MOBILE_BOOT_AUTH_CHECK"
  | "MOBILE_BOOT_AUTH_REQUIRED"
  | "MOBILE_BOOT_API_FAILED"
  | "MOBILE_BOOT_STALE_BUILD"
  | "MOBILE_BOOT_READY"
  | "MOBILE_BOOT_TIMEOUT"
  | "MOBILE_BOOT_RECOVERY";

/** production console spam 금지 — 개발/명시 플래그만 */
export function logMobileBoot(
  event: MobileBootEvent,
  detail?: Record<string, unknown>,
): void {
  if (typeof window === "undefined") {
    return;
  }
  const enabled =
    process.env.NODE_ENV !== "production" ||
    window.localStorage.getItem("stock-mobile-boot-debug") === "1";
  if (!enabled) {
    return;
  }
  // token/cookie 금지 — event + 안전한 메타만
  // eslint-disable-next-line no-console
  console.info(`[${event}]`, detail ?? {});
}

export function isChunkLoadFailureMessage(message: string): boolean {
  return /Loading chunk|ChunkLoadError|Failed to fetch dynamically imported module|\/_next\/static\//i.test(
    message,
  );
}

export function hasBootRecoveryAttempted(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return window.sessionStorage.getItem(MOBILE_BOOT_RECOVERY_KEY) === "1";
  } catch {
    return true;
  }
}

export function markBootRecoveryAttempted(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.setItem(MOBILE_BOOT_RECOVERY_KEY, "1");
  } catch {
    /* ignore */
  }
}

/** stale SW/cache 정리 후 1회 reload. 이미 시도했으면 false. */
export async function tryStaleClientRecovery(reason: string): Promise<boolean> {
  if (typeof window === "undefined") {
    return false;
  }
  if (hasBootRecoveryAttempted()) {
    logMobileBoot("MOBILE_BOOT_STALE_BUILD", {
      reason,
      recovered: false,
      loopGuard: true,
    });
    return false;
  }
  markBootRecoveryAttempted();
  logMobileBoot("MOBILE_BOOT_RECOVERY", { reason });
  try {
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((reg) => reg.unregister()));
    }
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(
            (key) =>
              key.startsWith("stock-mobile-shell-") ||
              key.includes("next") ||
              key.includes("workbox"),
          )
          .map((key) => caches.delete(key)),
      );
    }
  } catch {
    /* insecure context 등 */
  }
  window.location.reload();
  return true;
}
