"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, Col, Row, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function ComponentTag({
  name,
  status,
}: {
  name: string;
  status: unknown;
}) {
  const normalized = String(status ?? "UNKNOWN").toUpperCase();
  const color =
    normalized === "UP" || normalized === "CONFIGURED" || normalized === "OK"
      ? "success"
      : normalized === "DOWN" || normalized === "FAILED" || normalized === "ERROR"
        ? "error"
        : "warning";
  return (
    <Tag color={color}>
      {name}: {normalized}
    </Tag>
  );
}

export default function AdminMonitoringPage() {
  const health = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: adminApi.getHealth,
    refetchInterval: 15_000,
  });
  const version = useQuery({
    queryKey: queryKeys.system.version(),
    queryFn: adminApi.getVersion,
  });
  const system = useQuery({
    queryKey: queryKeys.system.dashboard({}),
    queryFn: () => adminApi.getSystemDashboard({ recent_limit: 20 }),
  });
  const quality = useQuery({
    queryKey: queryKeys.admin.marketQuality(),
    queryFn: adminApi.getMarketQualityDashboard,
  });
  const risk = useQuery({
    queryKey: queryKeys.dashboard.risk(),
    queryFn: () => adminApi.getRiskDashboard(),
  });
  const ollama = useQuery({
    queryKey: queryKeys.admin.ollamaStatus(),
    queryFn: adminApi.getOllamaStatus,
    refetchInterval: 15_000,
  });
  const migration = useQuery({
    queryKey: queryKeys.admin.opsMigration(),
    queryFn: adminApi.getOpsMigrationStatus,
  });

  const healthObj = asRecord(health.data);
  const components = asRecord(healthObj?.components) ?? {};
  const ollamaObj = asRecord(ollama.data);
  const migrationObj = asRecord(migration.data);

  return (
    <AdminPageShell
      title="시스템 모니터링"
      description="health · Ollama · Migration · system/dashboard · risk"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="컴포넌트 상태" loading={health.isLoading}>
          <Space wrap>
            <ComponentTag name="Overall" status={healthObj?.status} />
            <ComponentTag
              name="DB"
              status={asRecord(components.database)?.status}
            />
            <ComponentTag
              name="Ollama"
              status={
                ollamaObj?.status ?? asRecord(components.ollama)?.status
              }
            />
            <ComponentTag
              name="Scheduler"
              status={asRecord(components.scheduler)?.status}
            />
            <ComponentTag
              name="Kiwoom"
              status={asRecord(components.kiwoom_rest)?.status}
            />
            <Tag color={migrationObj?.in_sync ? "success" : "warning"}>
              Migration: {migrationObj?.in_sync ? "IN SYNC" : "DRIFT"} (
              {cell(migrationObj?.current)})
            </Tag>
          </Space>
          {health.error ? (
            <Typography.Text type="danger">
              {toApiError(health.error).message}
            </Typography.Text>
          ) : null}
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}>
            <AdminJsonCard
              title="GET /health"
              loading={health.isLoading}
              error={health.error ? toApiError(health.error) : null}
              data={health.data}
            />
          </Col>
          <Col xs={24} md={12}>
            <AdminJsonCard
              title="GET /version"
              loading={version.isLoading}
              error={version.error ? toApiError(version.error) : null}
              data={version.data}
            />
          </Col>
          <Col xs={24} md={12}>
            <AdminJsonCard
              title="GET /market-quality/dashboard"
              loading={quality.isLoading}
              error={quality.error ? toApiError(quality.error) : null}
              data={quality.data}
            />
          </Col>
          <Col xs={24} md={12}>
            <AdminJsonCard
              title="GET /dashboard/risk"
              loading={risk.isLoading}
              error={risk.error ? toApiError(risk.error) : null}
              data={risk.data}
            />
          </Col>
          <Col xs={24}>
            <AdminJsonCard
              title="GET /system/dashboard"
              loading={system.isLoading}
              error={system.error ? toApiError(system.error) : null}
              data={system.data}
            />
          </Col>
        </Row>
      </Space>
    </AdminPageShell>
  );
}
