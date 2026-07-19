"use client";

import { Suspense } from "react";
import { Flex, Spin } from "antd";

import { LoginForm } from "@/features/auth/components/LoginForm";

export default function LoginPage() {
  return (
    <Flex
      align="center"
      justify="center"
      style={{
        minHeight: "100vh",
        padding: 24,
        background:
          "radial-gradient(circle at top left, rgba(22,119,255,0.12), transparent 40%), var(--app-bg)",
      }}
    >
      <Suspense fallback={<Spin tip="로그인 준비 중..." />}>
        <LoginForm />
      </Suspense>
    </Flex>
  );
}
