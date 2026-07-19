"use client";

import { Button, Card, Flex, Form, Input, Space, Typography } from "antd";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { adminRoutes, userRoutes } from "@/config/routes";
import { env } from "@/config/env";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type { LoginRequest } from "@/features/auth/types/auth";
import { toApiError } from "@/lib/api/apiError";

function NoticeBanner({
  tone,
  title,
  description,
}: {
  tone: "warning" | "error";
  title: string;
  description?: string;
}) {
  const border = tone === "warning" ? "1px solid #faad14" : "1px solid #ff4d4f";
  const background =
    tone === "warning" ? "rgba(250, 173, 20, 0.08)" : "rgba(255, 77, 79, 0.08)";

  return (
    <div style={{ border, background, borderRadius: 8, padding: "12px 14px" }}>
      <Typography.Text strong>{title}</Typography.Text>
      {description ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 4 }}>
          {description}
        </Typography.Paragraph>
      ) : null}
    </div>
  );
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, enterAsDev } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const portal: "user" | "admin" =
    searchParams.get("portal") === "user" ? "user" : "admin";
  const nextParam = searchParams.get("next");
  const redirectTo =
    nextParam && nextParam.startsWith("/")
      ? nextParam
      : portal === "user"
        ? userRoutes.dashboard
        : adminRoutes.dashboard;

  const onFinish = async (values: LoginRequest) => {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await login(values, redirectTo);
    } catch (error) {
      setErrorMessage(toApiError(error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const onEnterDev = async () => {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await enterAsDev(portal, redirectTo);
    } catch (error) {
      setErrorMessage(toApiError(error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const subtitle = portal === "user" ? "User Web 입장" : "Admin 입장";

  return (
    <Card style={{ width: "100%", maxWidth: 420 }}>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            {env.APP_NAME}
          </Typography.Title>
          <Typography.Text type="secondary">{subtitle}</Typography.Text>
        </div>

        {errorMessage ? <NoticeBanner tone="error" title={errorMessage} /> : null}

        {env.AUTH_MODE === "disabled" ? (
          <Flex vertical gap={12}>
            <NoticeBanner
              tone="warning"
              title="회원 JWT 로그인은 Backend에 없습니다"
              description="개발 모드로 입장하면 로컬 세션만 생성합니다. /auth/login · /me API 미구현."
            />
            <Button type="primary" block loading={submitting} onClick={() => void onEnterDev()}>
              개발 모드로 입장 ({portal})
            </Button>
            <Button type="link" onClick={() => router.push("/")}>
              포털로 돌아가기
            </Button>
          </Flex>
        ) : (
          <Form<LoginRequest> layout="vertical" onFinish={(values) => void onFinish(values)}>
            <Form.Item
              label="Username"
              name="username"
              rules={[{ required: true, message: "사용자명을 입력하세요" }]}
            >
              <Input autoComplete="username" />
            </Form.Item>
            <Form.Item
              label="Password"
              name="password"
              rules={[{ required: true, message: "비밀번호를 입력하세요" }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting}>
              로그인
            </Button>
          </Form>
        )}
      </Space>
    </Card>
  );
}
