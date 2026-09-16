"use client";

import { Button, Card, Space, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { authRoutes, userRoutes } from "@/config/routes";
import { completeOnboarding } from "@/features/auth/api/authApi";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useAuthStore } from "@/features/auth/store/authStore";
import { resolvePostLoginPath } from "@/features/auth/utils/roles";
import { toApiError } from "@/lib/api/apiError";

export default function OnboardingPage() {
  const router = useRouter();
  const { authenticated, hydrated, user } = useAuth();
  const setSession = useAuthStore((s) => s.setSession);
  const accessToken = useAuthStore((s) => s.accessToken);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (hydrated && !authenticated) {
    router.replace(authRoutes.login);
  }

  const finish = async () => {
    setLoading(true);
    setError(null);
    try {
      const updated = await completeOnboarding();
      if (accessToken) {
        setSession(accessToken, updated, refreshToken ?? undefined);
      }
      router.replace(resolvePostLoginPath(updated));
    } catch (e) {
      setError(toApiError(e).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <Card style={{ maxWidth: 560, width: "100%" }}>
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            시작하기
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            환영합니다{user?.displayName ? `, ${user.displayName}` : ""}. 키움·업비트
            계좌는 필수가 아닙니다. 「내 계좌」에서 원하는 거래소만 연결하거나 Paper
            Trading만 사용할 수 있습니다.
          </Typography.Paragraph>
          <Typography.Text>
            다음 단계 안내: 프로필 확인 → 계좌 연결(선택) → 리스크·알림 설정
          </Typography.Text>
          {error ? <Typography.Text type="danger">{error}</Typography.Text> : null}
          <Space wrap>
            <Button type="primary" loading={loading} onClick={() => void finish()}>
              온보딩 완료 · 대시보드
            </Button>
            <Link href={userRoutes.accounts}>
              <Button>내 계좌로 이동</Button>
            </Link>
          </Space>
        </Space>
      </Card>
    </div>
  );
}
