"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, Col, Row, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { SettingsEditor } from "@/features/admin/components/SettingsEditor";
import { OllamaRoleModelPanel } from "@/features/admin/ollama/OllamaRoleModelPanel";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** 역할 모델은 전용 Select UI에서 관리 — SettingsEditor와 중복 편집 방지 */
const ROLE_MODEL_SETTING_KEYS = [
  "analysis_llm_model",
  "trading_llm_model",
  "teacher_llm_model",
  "ollama_model",
];

export default function AdminOllamaPage() {
  const statusQuery = useQuery({
    queryKey: queryKeys.admin.ollamaStatus(),
    queryFn: adminApi.getOllamaStatus,
    refetchInterval: 15_000,
  });

  const status = asRecord(statusQuery.data);

  return (
    <AdminPageShell
      title="Ollama 관리"
      description="역할별 모델 · 설치 목록 · AI 연결 설정"
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
                fallback model: {cell(status?.configured_model)}
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

        <OllamaRoleModelPanel />

        <Row gutter={[16, 16]}>
          <Col xs={24}>
            <Card title="AI 연결 설정 (DB)" size="small">
              <SettingsEditor
                category="ai"
                excludeKeys={ROLE_MODEL_SETTING_KEYS}
              />
            </Card>
          </Col>
        </Row>
      </Space>
    </AdminPageShell>
  );
}
