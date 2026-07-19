"use client";

import { Flex } from "antd";

import { SignupForm } from "@/features/auth/components/SignupForm";

export default function SignupPage() {
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
      <SignupForm />
    </Flex>
  );
}
