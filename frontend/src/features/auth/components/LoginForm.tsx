"use client";

import { Button, Card, Checkbox, Collapse, Divider, Form, Input, Space, Typography } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { authRoutes } from "@/config/routes";
import { env } from "@/config/env";
import {
  fetchGoogleOAuthStatus,
  googleLoginStartUrl,
} from "@/features/auth/api/authApi";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type { LoginRequest } from "@/features/auth/types/auth";
import { resolvePostLoginPath } from "@/features/auth/utils/roles";
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
  const { login, authenticated, hydrated, user, hydrateFromStorage } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  const nextParam = searchParams.get("next");
  const redirectTo =
    nextParam && nextParam.startsWith("/") ? nextParam : undefined;
  const oauthError = searchParams.get("error");

  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  useEffect(() => {
    if (oauthError) {
      setErrorMessage("Google 로그인에 실패했습니다. 다시 로그인해 주세요.");
    }
  }, [oauthError]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const status = await fetchGoogleOAuthStatus();
        if (!cancelled) {
          setGoogleEnabled(Boolean(status.enabled));
        }
      } catch {
        if (!cancelled) {
          setGoogleEnabled(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!hydrated || !authenticated || !user) {
      return;
    }
    router.replace(resolvePostLoginPath(user, redirectTo ?? null));
  }, [authenticated, hydrated, user, redirectTo, router]);

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

  const onGoogleLogin = () => {
    setGoogleLoading(true);
    setErrorMessage(null);
    const next =
      redirectTo ||
      (typeof window !== "undefined" &&
      (window.matchMedia("(display-mode: standalone)").matches ||
        window.innerWidth < 768)
        ? "/mobile"
        : undefined);
    window.location.assign(googleLoginStartUrl(next));
  };

  if (hydrated && authenticated) {
    return (
      <Card style={{ width: "100%", maxWidth: 420 }}>
        <Typography.Text type="secondary">권한별 화면으로 이동 중…</Typography.Text>
      </Card>
    );
  }

  return (
    <Card style={{ width: "100%", maxWidth: 420 }}>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            {env.APP_NAME}
          </Typography.Title>
          <Typography.Text type="secondary">
            통합 로그인 — 권한에 따라 사용자/관리자 화면으로 이동합니다
          </Typography.Text>
        </div>

        {errorMessage ? <NoticeBanner title={errorMessage} /> : null}

        {googleEnabled ? (
          <Button
            type="primary"
            size="large"
            block
            loading={googleLoading}
            onClick={onGoogleLogin}
            style={{
              background: "#fff",
              color: "#1f1f1f",
              borderColor: "#dadce0",
              fontWeight: 500,
            }}
          >
            Google로 로그인
          </Button>
        ) : (
          <Typography.Text type="secondary">
            Google 로그인은 관리자 설정 후 활성화됩니다. 그동안 기존 계정으로
            로그인하세요.
          </Typography.Text>
        )}

        <Divider plain>또는</Divider>

        <Collapse
          ghost
          defaultActiveKey={googleEnabled ? [] : ["password"]}
          items={[
            {
              key: "password",
              label: "기존 계정으로 로그인",
              children: (
                <Form
                  layout="vertical"
                  onFinish={(values) => void onFinish(values)}
                  initialValues={{ rememberMe: true }}
                >
                  <Form.Item
                    label="아이디 또는 이메일"
                    name="username"
                    rules={[
                      {
                        required: true,
                        message: "아이디 또는 이메일을 입력하세요",
                      },
                    ]}
                  >
                    <Input
                      autoComplete="username"
                      placeholder="hong 또는 hong@example.com"
                    />
                  </Form.Item>
                  <Form.Item
                    label="비밀번호"
                    name="password"
                    rules={[
                      { required: true, message: "비밀번호를 입력하세요" },
                    ]}
                  >
                    <Input.Password autoComplete="current-password" />
                  </Form.Item>
                  <Form.Item name="rememberMe" valuePropName="checked">
                    <Checkbox>로그인 상태 유지</Checkbox>
                  </Form.Item>
                  <Button
                    type="default"
                    htmlType="submit"
                    loading={submitting}
                    block
                  >
                    로그인
                  </Button>
                </Form>
              ),
            },
          ]}
        />

        <Typography.Text type="secondary">
          계정이 없나요? <Link href={authRoutes.signup}>회원가입</Link>
        </Typography.Text>
      </Space>
    </Card>
  );
}
