"use client";

import { Button, Card, Checkbox, Form, Input, Space, Typography } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { adminRoutes, routes, userRoutes } from "@/config/routes";
import { env } from "@/config/env";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type { LoginRequest } from "@/features/auth/types/auth";
import { toApiError } from "@/lib/api/apiError";

function NoticeBanner({ title, description }: { title: string; description?: string }) {
  return (
    <div
      style={{
        border: "1px solid #ff4d4f",
        background: "rgba(255, 77, 79, 0.08)",
        borderRadius: 8,
        padding: "12px 14px",
      }}
    >
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
  const { login } = useAuth();
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

  const onFinish = async (values: LoginRequest & { rememberMe?: boolean }) => {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await login(
        {
          username: values.username,
          password: values.password,
          rememberMe: Boolean(values.rememberMe),
        },
        redirectTo,
      );
    } catch (error) {
      setErrorMessage(toApiError(error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card style={{ width: "100%", maxWidth: 420 }}>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            {env.APP_NAME}
          </Typography.Title>
          <Typography.Text type="secondary">
            {portal === "user" ? "User 로그인" : "Admin 로그인"}
          </Typography.Text>
        </div>

        {errorMessage ? <NoticeBanner title={errorMessage} /> : null}

        <Form
          layout="vertical"
          onFinish={(values) => void onFinish(values)}
          initialValues={{ rememberMe: true }}
        >
          <Form.Item
            label="아이디 또는 이메일"
            name="username"
            rules={[{ required: true, message: "아이디 또는 이메일을 입력하세요" }]}
          >
            <Input autoComplete="username" placeholder="hong 또는 hong@example.com" />
          </Form.Item>
          <Form.Item
            label="비밀번호"
            name="password"
            rules={[{ required: true, message: "비밀번호를 입력하세요" }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item name="rememberMe" valuePropName="checked">
            <Checkbox>자동 로그인 (이 기기에서 유지)</Checkbox>
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            로그인
          </Button>
          <Button type="link" block href={routes.signup}>
            회원가입
          </Button>
          <Button type="link" block onClick={() => router.push("/")}>
            포털로 돌아가기
          </Button>
        </Form>

        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          계정이 없으면 <Link href={routes.signup}>회원가입</Link> 후 이용하세요.
          {portal === "admin" ? (
            <>
              {" "}
              Admin 콘솔은 <Typography.Text code>admin</Typography.Text> /
              <Typography.Text code>operator</Typography.Text>(trader) 역할만
              진입할 수 있습니다. viewer는 User로 이동합니다.
            </>
          ) : null}
        </Typography.Paragraph>
      </Space>
    </Card>
  );
}
