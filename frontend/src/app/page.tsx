"use client";

import Link from "next/link";
import { Button, Card, Flex, Space, Typography } from "antd";

import { adminRoutes, userRoutes } from "@/config/routes";
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
            투자자용 User Web과 관리자 Admin을 선택하세요. 회원가입 후 로그인하거나,
            기존 계정으로 로그인하세요.
          </Typography.Paragraph>
          <Flex gap={12} wrap>
            <Link href={`${userRoutes.login}?portal=user&next=${encodeURIComponent(userRoutes.dashboard)}`}>
              <Button type="primary" size="large">
                User 로그인
              </Button>
            </Link>
            <Link
              href={`${adminRoutes.login}?portal=admin&next=${encodeURIComponent(adminRoutes.dashboard)}`}
            >
              <Button size="large">Admin 로그인</Button>
            </Link>
            <Link href="/signup">
              <Button size="large">회원가입</Button>
            </Link>
          </Flex>
          <Typography.Text type="secondary">
            이미 세션이 있으면{" "}
            <Link href={userRoutes.dashboard}>/user/dashboard</Link> ·{" "}
            <Link href={adminRoutes.dashboard}>/admin/dashboard</Link>
          </Typography.Text>
        </Space>
      </Card>
    </Flex>
  );
}
