"use client";

import { useEffect } from "react";

import {
  logMobileBoot,
} from "@/features/mobile/mobileBootRecovery";

/**
 * 모바일 진입 시 구 SW를 제거한다.
 * (V1 SW HTML-for-JS fallback + next dev HMR 충돌 시 리로드 루프 유발)
 * PWA SW 재등록은 안정화 후 별도 작업으로 켠다.
 */
export function RegisterMobileServiceWorker() {
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const path = window.location.pathname;
    if (!path.startsWith("/mobile")) {
      return;
    }

    let cancelled = false;

    void (async () => {
      try {
        if ("serviceWorker" in navigator) {
          const regs = await navigator.serviceWorker.getRegistrations();
          if (regs.length > 0) {
            logMobileBoot("MOBILE_BOOT_STALE_BUILD", {
              action: "unregister_sw",
              count: regs.length,
            });
          }
          await Promise.all(regs.map((reg) => reg.unregister()));
        }
        if ("caches" in window) {
          const keys = await caches.keys();
          await Promise.all(
            keys
              .filter((key) => key.startsWith("stock-mobile-shell-"))
              .map((key) => caches.delete(key)),
          );
        }
        if (cancelled) {
          return;
        }
      } catch {
        /* insecure context 등은 무시 */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}
