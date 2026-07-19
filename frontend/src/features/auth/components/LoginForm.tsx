"use client";

import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import { useState } from "react";

import { env } from "@/config/env";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type { LoginRequest } from "@/features/auth/types/auth";
import { toApiError } from "@/lib/api/apiError";

export function LoginForm() {
  const { login, enterAsDev } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const onFinish = async (values: LoginRequest) => {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await login(values);
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
      await enterAsDev();
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
          <Typography.Text type="secondary">관리자 로그인</Typography.Text>
        </div>

        {errorMessage ? <Alert type="error" message={errorMessage} showIcon /> : null}

        {env.AUTH_MODE === "disabled" ? (
          <>
            <Alert
              type="warning"
              showIcon
              message="인증 API가 비활성화되어 있습니다"
              description="개발 모드로 입장하면 로컬 세션만 생성합니다. TODO(STEP50)"
            />
            <Button type="primary" block loading={submitting} onClick={() => void onEnterDev()}>
              개발 모드로 입장
            </Button>
          </>
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
