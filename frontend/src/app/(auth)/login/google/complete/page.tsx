"use client";

import { Button, Card, Typography } from "antd";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { authRoutes } from "@/config/routes";
import {
  completeGoogleLogin,
  persistRefreshToken,
} from "@/features/auth/api/authApi";
import { useAuthStore } from "@/features/auth/store/authStore";
import { resolvePostLoginPath } from "@/features/auth/utils/roles";
import { toApiError } from "@/lib/api/apiError";

function GoogleCompleteInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setSession = useAuthStore((s) => s.setSession);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const err = searchParams.get("error");
    if (err) {
      setError(err);
      return;
    }
    const code = searchParams.get("code");
    if (!code) {
      setError("Google 로그인 코드가 없습니다.");
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
        router.replace(resolvePostLoginPath(user, null));
      } catch (e) {
        if (!cancelled) {
          setError(toApiError(e).message);
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
        <Typography.Paragraph type="danger">{error}</Typography.Paragraph>
        <Button type="primary" href={authRoutes.login} block>
          로그인으로 돌아가기
        </Button>
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
