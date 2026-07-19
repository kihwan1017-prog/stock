"use client";

import { Flex } from "antd";

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
      <LoginForm />
    </Flex>
  );
}
