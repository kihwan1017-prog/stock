"use client";

import { Button, Card, Checkbox, Form, Input, Space, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { env } from "@/config/env";
import { routes, userRoutes } from "@/config/routes";
import {
  checkEmailAvailable,
  checkUsernameAvailable,
} from "@/features/auth/api/authApi";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type { SignupRequest } from "@/features/auth/types/auth";
import { toApiError } from "@/lib/api/apiError";

export function SignupForm() {
  const router = useRouter();
  const { signup } = useAuth();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const onFinish = async (values: {
    name: string;
    username: string;
    email: string;
    password: string;
    passwordConfirm: string;
    termsAccepted: boolean;
  }) => {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const payload: SignupRequest = {
        name: values.name,
        username: values.username,
        email: values.email,
        password: values.password,
        passwordConfirm: values.passwordConfirm,
        termsAccepted: values.termsAccepted,
      };
      await signup(payload, userRoutes.dashboard);
    } catch (error) {
      setErrorMessage(toApiError(error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card style={{ width: "100%", maxWidth: 480 }}>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            회원가입
          </Typography.Title>
          <Typography.Text type="secondary">{env.APP_NAME}</Typography.Text>
        </div>

        {errorMessage ? (
          <div
            style={{
              border: "1px solid #ff4d4f",
              background: "rgba(255, 77, 79, 0.08)",
              borderRadius: 8,
              padding: "12px 14px",
            }}
          >
            <Typography.Text strong>{errorMessage}</Typography.Text>
          </div>
        ) : null}

        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => void onFinish(values)}
          initialValues={{ termsAccepted: false }}
        >
          <Form.Item
            label="이름"
            name="name"
            rules={[{ required: true, message: "이름을 입력하세요" }]}
          >
            <Input autoComplete="name" />
          </Form.Item>
          <Form.Item
            label="아이디"
            name="username"
            rules={[
              { required: true, message: "아이디를 입력하세요" },
              { min: 3, message: "아이디는 3자 이상" },
              {
                pattern: /^[a-zA-Z][a-zA-Z0-9_-]*$/,
                message: "영문으로 시작하고 영문·숫자·-_ 만 사용",
              },
              {
                validator: async (_, value) => {
                  if (!value || String(value).length < 3) return;
                  const result = await checkUsernameAvailable(String(value));
                  if (!result.available) {
                    throw new Error("이미 사용 중인 아이디입니다");
                  }
                },
              },
            ]}
            validateDebounce={400}
          >
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item
            label="이메일"
            name="email"
            rules={[
              { required: true, message: "이메일을 입력하세요" },
              { type: "email", message: "올바른 이메일을 입력하세요" },
              {
                validator: async (_, value) => {
                  if (!value || !String(value).includes("@")) return;
                  const result = await checkEmailAvailable(String(value));
                  if (!result.available) {
                    throw new Error("이미 사용 중인 이메일입니다");
                  }
                },
              },
            ]}
            validateDebounce={400}
          >
            <Input autoComplete="email" />
          </Form.Item>
          <Form.Item
            label="비밀번호"
            name="password"
            rules={[
              { required: true, message: "비밀번호를 입력하세요" },
              { min: 8, message: "비밀번호는 8자 이상" },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            label="비밀번호 확인"
            name="passwordConfirm"
            dependencies={["password"]}
            rules={[
              { required: true, message: "비밀번호 확인을 입력하세요" },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue("password") === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error("비밀번호가 일치하지 않습니다"));
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="termsAccepted"
            valuePropName="checked"
            rules={[
              {
                validator: (_, value) =>
                  value
                    ? Promise.resolve()
                    : Promise.reject(new Error("약관에 동의해야 합니다")),
              },
            ]}
          >
            <Checkbox>
              서비스 이용약관 및 개인정보 처리방침에 동의합니다 (필수)
            </Checkbox>
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            가입하고 시작하기
          </Button>
          <Button type="link" block href={routes.login}>
            이미 계정이 있어요 — 로그인
          </Button>
          <Button type="link" block onClick={() => router.push("/")}>
            포털로 돌아가기
          </Button>
        </Form>

        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          가입 완료 시 자동 로그인되며 User 화면으로 이동합니다. Admin 메뉴는 관리자
          권한이 필요합니다. <Link href={routes.login}>로그인</Link>
        </Typography.Paragraph>
      </Space>
    </Card>
  );
}
