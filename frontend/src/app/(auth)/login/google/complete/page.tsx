"use client";

import { Button, Card, Space, Typography } from "antd";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { authRoutes } from "@/config/routes";
import {
  completeGoogleLogin,
  googleLoginStartUrl,
  persistRefreshToken,
} from "@/features/auth/api/authApi";
import { useAuthStore } from "@/features/auth/store/authStore";
import { resolvePostLoginPath } from "@/features/auth/utils/roles";

const FRIENDLY_FAIL =
  "Google 로그인에 실패했습니다. 다시 로그인해 주세요.";

function GoogleCompleteInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setSession = useAuthStore((s) => s.setSession);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const err = searchParams.get("error");
    if (err) {
      // raw verifier 문구는 사용자에게 노출하지 않음
      setError(FRIENDLY_FAIL);
      if (typeof console !== "undefined") {
        console.warn("[google-oauth] callback error present (details omitted)");
      }
      return;
    }
    const code = searchParams.get("code");
    if (!code) {
      setError(FRIENDLY_FAIL);
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const response = await completeGoogleLogin(code);
        if (cancelled) return;
        const user = {
          ...response.user,
          defaultRoute: response.defaultRoute ?? response.user.defaultRoute,
        };
        setSession(response.accessToken, user, response.refreshToken, true);
        persistRefreshToken(response.refreshToken);
        // PWA/모바일 기본 착지 — admin이면 /mobile
        const roles = user.roles || [];
        const preferMobile =
          typeof window !== "undefined" &&
          (window.matchMedia("(display-mode: standalone)").matches ||
            window.innerWidth < 768 ||
            roles.includes("admin"));
        const next = preferMobile && roles.includes("admin")
          ? "/mobile"
          : resolvePostLoginPath(user, null);
        router.replace(next);
      } catch (e) {
        if (!cancelled) {
          setError(FRIENDLY_FAIL);
          if (typeof console !== "undefined") {
            console.warn("[google-oauth] complete failed", e);
          }
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router, searchParams, setSession]);

  if (error) {
    return (
      <Card style={{ width: "100%", maxWidth: 420 }}>
        <Typography.Title level={4}>Google 로그인 실패</Typography.Title>
        <Typography.Paragraph>{error}</Typography.Paragraph>
        <Space orientation="vertical" style={{ width: "100%" }} size="middle">
          <Button
            type="primary"
            block
            onClick={() => {
              window.location.assign(googleLoginStartUrl("/mobile"));
            }}
          >
            Google로 다시 로그인
          </Button>
          <Button href={authRoutes.login} block>
            로그인 화면으로 돌아가기
          </Button>
        </Space>
      </Card>
    );
  }

  return (
    <Card style={{ width: "100%", maxWidth: 420 }}>
      <Typography.Text type="secondary">Google 로그인 처리 중…</Typography.Text>
    </Card>
  );
}

export default function GoogleCompletePage() {
  return (
    <Suspense
      fallback={
        <Card style={{ width: "100%", maxWidth: 420 }}>
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        </Card>
      }
    >
      <GoogleCompleteInner />
    </Suspense>
  );
}
