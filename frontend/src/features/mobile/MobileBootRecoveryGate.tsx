"use client";

import { useEffect, useState } from "react";
import { Button, Result } from "antd";

import { authRoutes } from "@/config/routes";
import {
  SPLASH_MAX_DURATION_MS,
  hasBootRecoveryAttempted,
  isChunkLoadFailureMessage,
  logMobileBoot,
  tryStaleClientRecovery,
} from "@/features/mobile/mobileBootRecovery";

/**
 * 루트/모바일 공통 — ChunkLoadError·장기 미준비 시 terminal UX.
 * AuthGuard보다 바깥에서도 동작하도록 AppProviders 하위에 둔다.
 */
export function MobileBootRecoveryGate() {
  const [fatal, setFatal] = useState<string | null>(null);

  useEffect(() => {
    logMobileBoot("MOBILE_BOOT_START", {
      path: window.location.pathname,
    });

    const onError = (event: ErrorEvent) => {
      const msg = String(event.message || event.error || "");
      if (!isChunkLoadFailureMessage(msg)) {
        return;
      }
      void (async () => {
        const started = await tryStaleClientRecovery("chunk_load_error");
        if (!started) {
          setFatal("stale_build");
        }
      })();
    };

    const onRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      const msg =
        typeof reason === "string"
          ? reason
          : String((reason as { message?: string })?.message || reason || "");
      if (!isChunkLoadFailureMessage(msg)) {
        return;
      }
      void (async () => {
        const started = await tryStaleClientRecovery("chunk_load_rejection");
        if (!started) {
          setFatal("stale_build");
        }
      })();
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);

    // 문서만 뜨고 hydrate/ready 마커가 없으면(예: chunk 실패) terminal UX
    const timer = window.setTimeout(() => {
      const path = window.location.pathname;
      if (!path.startsWith("/mobile")) {
        return;
      }
      if (
        document.documentElement.getAttribute("data-mobile-boot-ready") === "1"
      ) {
        logMobileBoot("MOBILE_BOOT_READY");
        return;
      }
      logMobileBoot("MOBILE_BOOT_TIMEOUT", { path });
      // 1회만 stale recovery — 루프 금지
      if (!hasBootRecoveryAttempted()) {
        void tryStaleClientRecovery("boot_timeout");
        return;
      }
      setFatal("timeout");
    }, SPLASH_MAX_DURATION_MS);

    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
      window.clearTimeout(timer);
    };
  }, []);

  if (!fatal) {
    return null;
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "#0f1419",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <Result
        status="error"
        title="앱을 불러오지 못했습니다"
        subTitle={
          fatal === "stale_build"
            ? "이전 버전 캐시와 충돌했을 수 있습니다. 다시 시도하거나 로그인 화면으로 이동해 주세요."
            : "연결 상태를 확인한 뒤 다시 시도해 주세요. Tailscale이 켜져 있는지 확인해 주세요."
        }
        extra={[
          <Button
            type="primary"
            key="retry"
            onClick={() => {
              window.location.reload();
            }}
          >
            다시 시도
          </Button>,
          <Button
            key="login"
            href={authRoutes.login}
            onClick={() => {
              window.location.assign(authRoutes.login);
            }}
          >
            로그인 화면으로 이동
          </Button>,
        ]}
      />
    </div>
  );
}
