"use client";

import { Button, Card, Descriptions, Space, Typography } from "antd";

import { env } from "@/config/env";
import { openApiDocsUrl } from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";

export default function AdminApiPage() {
  const docsUrl = openApiDocsUrl();
  const openApiUrl = docsUrl.replace(/\/docs\/?$/, "/openapi.json");

  return (
    <AdminPageShell title="API 문서" description="FastAPI OpenAPI · 인증 · 주요 그룹 안내">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card title="OpenAPI" size="small">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Base URL">{env.API_BASE_URL}</Descriptions.Item>
            <Descriptions.Item label="Prefix">{env.API_PREFIX}</Descriptions.Item>
            <Descriptions.Item label="Swagger">
              <Typography.Link href={docsUrl} target="_blank" rel="noreferrer">
                {docsUrl}
              </Typography.Link>
            </Descriptions.Item>
            <Descriptions.Item label="OpenAPI JSON">
              <Typography.Link href={openApiUrl} target="_blank" rel="noreferrer">
                {openApiUrl}
              </Typography.Link>
            </Descriptions.Item>
          </Descriptions>
          <Button type="primary" href={docsUrl} target="_blank" style={{ marginTop: 12 }}>
            Swagger UI 열기
          </Button>
        </Card>

        <Card title="인증" size="small">
          <Typography.Paragraph>
            Admin Web은 <Typography.Text code>JWT</Typography.Text> (로그인)을
            사용합니다. 스크립트·운영 API는{" "}
            <Typography.Text code>X-Admin-API-Key</Typography.Text> 또는 admin JWT를
            허용합니다.
          </Typography.Paragraph>
          <ul style={{ marginBottom: 0 }}>
            <li>
              <Typography.Text code>POST /api/v1/auth/login</Typography.Text> — 토큰 발급
            </li>
            <li>
              <Typography.Text code>Authorization: Bearer …</Typography.Text> — 회원·설정·문서
            </li>
            <li>
              <Typography.Text code>X-Admin-API-Key</Typography.Text> — 감사·Kill Switch·live
              transition 등
            </li>
          </ul>
        </Card>

        <Card title="주요 API 그룹" size="small">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="Auth / RBAC">
              /auth, /users, /roles
            </Descriptions.Item>
            <Descriptions.Item label="Settings">
              /settings, /ollama/*
            </Descriptions.Item>
            <Descriptions.Item label="Trading">
              /order-execution/submit, /orders, /paper-*, /strategy-deployments
            </Descriptions.Item>
            <Descriptions.Item label="Risk">
              /risk/kill-switch, /risk/daily-loss, /risk-policies
            </Descriptions.Item>
            <Descriptions.Item label="Ops">
              /audit/events, /ops/db/*, /jobs, /docs (문서 CMS)
            </Descriptions.Item>
          </Descriptions>
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            상세 표: 저장소 <Typography.Text code>docs/manual/API사용매뉴얼.md</Typography.Text>{" "}
            · <Typography.Text code>docs/backend/API.md</Typography.Text>. API 키
            게이트웨이 CRUD는 범위 밖입니다.
          </Typography.Paragraph>
        </Card>
      </Space>
    </AdminPageShell>
  );
}
