"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, Descriptions, Space, Typography } from "antd";

import { env } from "@/config/env";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import {
  SettingsEditor,
  SettingsHistoryPanel,
} from "@/features/admin/components/SettingsEditor";
import { ChangePasswordForm } from "@/features/auth/components/ChangePasswordForm";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminEnvSettingsPage() {
  const kiwoom = useQuery({
    queryKey: queryKeys.admin.kiwoomConfig(),
    queryFn: adminApi.getKiwoomConfiguration,
  });
  const health = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: adminApi.getHealth,
  });

  return (
    <AdminPageShell
      title="환경설정"
      description="통합·알림 설정 · Frontend 공개 환경 · 비밀번호 변경"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card title="Frontend 환경 (NEXT_PUBLIC_*)" size="small">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="APP_NAME">{env.APP_NAME}</Descriptions.Item>
            <Descriptions.Item label="API_BASE_URL">{env.API_BASE_URL}</Descriptions.Item>
            <Descriptions.Item label="API_PREFIX">{env.API_PREFIX}</Descriptions.Item>
            <Descriptions.Item label="AUTH_MODE">{env.AUTH_MODE}</Descriptions.Item>
          </Descriptions>
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            JWT Secret·Admin API Key·DB 비밀번호는 서버 env에만 둡니다.
            DB Settings에는 포함하지 않습니다.
          </Typography.Paragraph>
        </Card>

        <ChangePasswordForm />

        <Card title="환경설정 (DB)" size="small">
          <SettingsEditor category="environment" />
        </Card>

        <Card title="최근 설정 변경" size="small">
          <SettingsHistoryPanel />
        </Card>

        <AdminJsonCard
          title="GET /kiwoom/configuration"
          loading={kiwoom.isLoading}
          error={kiwoom.error ? toApiError(kiwoom.error) : null}
          data={kiwoom.data}
        />
        <AdminJsonCard
          title="GET /health"
          loading={health.isLoading}
          error={health.error ? toApiError(health.error) : null}
          data={health.data}
        />
      </Space>
    </AdminPageShell>
  );
}
