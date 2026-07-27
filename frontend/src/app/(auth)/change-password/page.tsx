"use client";

import { Button, Card, Form, Input, Space, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { authRoutes } from "@/config/routes";
import { changePassword } from "@/features/auth/api/authApi";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useAuthStore } from "@/features/auth/store/authStore";
import { resolvePostLoginPath } from "@/features/auth/utils/roles";
import { toApiError } from "@/lib/api/apiError";

export default function ChangePasswordPage() {
  const router = useRouter();
  const { authenticated, hydrated, user } = useAuth();
  const setSession = useAuthStore((s) => s.setSession);
  const accessToken = useAuthStore((s) => s.accessToken);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (hydrated && !authenticated) {
    router.replace(authRoutes.login);
  }

  const onFinish = async (values: {
    currentPassword: string;
    newPassword: string;
    confirmPassword: string;
  }) => {
    if (values.newPassword !== values.confirmPassword) {
      setError("새 비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await changePassword({
        currentPassword: values.currentPassword,
        newPassword: values.newPassword,
      });
      if (user && accessToken) {
        const updated = {
          ...user,
          passwordChangeRequired: false,
        };
        setSession(accessToken, updated, refreshToken ?? undefined);
        router.replace(resolvePostLoginPath(updated));
      } else {
        router.replace(authRoutes.login);
      }
    } catch (e) {
      setError(toApiError(e).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <FlexCenter>
      <Card style={{ width: "100%", maxWidth: 420 }}>
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          <div>
            <Typography.Title level={3} style={{ marginBottom: 4 }}>
              비밀번호 변경
            </Typography.Title>
            <Typography.Text type="secondary">
              최초 로그인 또는 정책에 따라 비밀번호 변경이 필요합니다.
            </Typography.Text>
          </div>
          {error ? (
            <Typography.Text type="danger">{error}</Typography.Text>
          ) : null}
          <Form layout="vertical" onFinish={(v) => void onFinish(v)}>
            <Form.Item
              name="currentPassword"
              label="현재 비밀번호"
              rules={[{ required: true }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Form.Item
              name="newPassword"
              label="새 비밀번호"
              rules={[{ required: true, min: 8 }]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Form.Item
              name="confirmPassword"
              label="새 비밀번호 확인"
              rules={[{ required: true }]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting} block>
              변경 후 계속
            </Button>
          </Form>
        </Space>
      </Card>
    </FlexCenter>
  );
}

function FlexCenter({ children }: { children: ReactNode }) {
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
      {children}
    </div>
  );
}
