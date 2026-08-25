"use client";

import { useEffect } from "react";

/** 모바일 셸에서만 SW 등록. API는 network-first (sw.js). */
export function RegisterMobileServiceWorker() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) {
      return;
    }
    const path = window.location.pathname;
    if (!path.startsWith("/mobile")) {
      return;
    }
    void navigator.serviceWorker.register("/sw-mobile.js").catch(() => {
      /* localhost/http 제한은 무시 */
    });
  }, []);
  return null;
}
