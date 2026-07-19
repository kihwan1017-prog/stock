"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, Col, Row, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { SettingsEditor } from "@/features/admin/components/SettingsEditor";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminOllamaPage() {
  const statusQuery = useQuery({
    queryKey: queryKeys.admin.ollamaStatus(),
    queryFn: adminApi.getOllamaStatus,
    refetchInterval: 15_000,
  });
  const modelsQuery = useQuery({
    queryKey: queryKeys.admin.ollamaModels(),
    queryFn: adminApi.listOllamaModels,
    retry: false,
  });

  const status = asRecord(statusQuery.data);

  return (
    <AdminPageShell
      title="Ollama 관리"
      description="상태 · 모델 · AI 설정"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" loading={statusQuery.isLoading} title="Ollama 상태">
          {statusQuery.error ? (
            <Typography.Text type="danger">
              {toApiError(statusQuery.error).message}
            </Typography.Text>
          ) : (
            <Space wrap>
              <Tag
                color={
                  String(status?.status).toUpperCase() === "UP"
                    ? "success"
                    : "error"
                }
              >
                {cell(status?.status)}
              </Tag>
              <Typography.Text code>{cell(status?.base_url)}</Typography.Text>
              <Typography.Text>
                model: {cell(status?.configured_model)}
              </Typography.Text>
              <Typography.Text>
                installed: {cell(status?.model_count)}
              </Typography.Text>
              {status?.message ? (
                <Typography.Text type="secondary">
                  {cell(status.message)}
                </Typography.Text>
              ) : null}
            </Space>
          )}
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card title="AI 설정 (DB)" size="small">
              <SettingsEditor category="ai" />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <AdminJsonCard
              title="설치된 모델 (GET /ollama/models)"
              loading={modelsQuery.isLoading}
              error={
                modelsQuery.error ? toApiError(modelsQuery.error) : null
              }
              data={modelsQuery.data}
            />
          </Col>
        </Row>
      </Space>
    </AdminPageShell>
  );
}
