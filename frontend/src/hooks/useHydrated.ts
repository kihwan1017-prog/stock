"use client";

import { useSyncExternalStore } from "react";

function subscribe(): () => void {
  return () => undefined;
}

/** 클라이언트 hydration 완료 여부 (SSR과 첫 페인트 불일치 방지) */
export function useHydrated(): boolean {
  return useSyncExternalStore(subscribe, () => true, () => false);
}
