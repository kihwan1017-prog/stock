"use client";

import Link from "next/link";
import { Button, Card, Flex, Space, Typography } from "antd";

import { authRoutes } from "@/config/routes";
import { env } from "@/config/env";

export default function PortalPage() {
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
      <Card style={{ maxWidth: 560, width: "100%" }}>
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Typography.Title level={2} style={{ margin: 0 }}>
            {env.APP_NAME}
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            플랫폼 로그인은 하나입니다. 로그인 후 DB 권한에 따라 사용자 또는 관리자
            화면으로 이동합니다. 키움·업비트 API 인증은 「내 계좌」에서 연결합니다.
          </Typography.Paragraph>
          <Flex gap={12} wrap>
            <Link href={authRoutes.login}>
              <Button type="primary" size="large">
                로그인
              </Button>
            </Link>
            <Link href={authRoutes.signup}>
              <Button size="large">회원가입</Button>
            </Link>
          </Flex>
        </Space>
      </Card>
    </Flex>
  );
}
