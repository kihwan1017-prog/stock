"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, Col, Descriptions, Row, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function StatusTag({ label, status }: { label: string; status: unknown }) {
  const normalized = String(status ?? "UNKNOWN").toUpperCase();
  const color =
    normalized === "UP" ||
    normalized === "CONFIGURED" ||
    normalized === "OK" ||
    normalized === "INACTIVE"
      ? "success"
      : normalized === "DOWN" ||
          normalized === "FAILED" ||
          normalized === "ERROR" ||
          normalized === "CRITICAL" ||
          normalized === "ACTIVE"
        ? "error"
        : "warning";
  return (
    <Tag color={color}>
      {label}: {normalized}
    </Tag>
  );
}

function SectionCard({
  title,
  data,
  loading,
  error,
}: {
  title: string;
  data: unknown;
  loading: boolean;
  error: unknown;
}) {
  return (
    <AdminJsonCard
      title={title}
      loading={loading}
      error={error ? toApiError(error) : null}
      data={data}
    />
  );
}

export default function AdminMonitoringPage() {
  const overview = useQuery({
    queryKey: queryKeys.system.monitoringOverview({}),
    queryFn: () =>
      adminApi.getMonitoringOverview({ evaluate_alerts: true }),
    refetchInterval: 15_000,
  });
  const live = useQuery({
    queryKey: queryKeys.system.healthLive(),
    queryFn: adminApi.getHealthLive,
    refetchInterval: 10_000,
  });
  const ready = useQuery({
    queryKey: queryKeys.system.healthReady(),
    queryFn: adminApi.getHealthReady,
    refetchInterval: 10_000,
  });
  const version = useQuery({
    queryKey: queryKeys.system.version(),
    queryFn: adminApi.getVersion,
  });
  const alerts = useQuery({
    queryKey: queryKeys.system.monitoringAlerts(),
    queryFn: () => adminApi.getMonitoringAlerts({ limit: 30 }),
    refetchInterval: 30_000,
  });
  const health = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: adminApi.getHealth,
    refetchInterval: 30_000,
  });

  const ov = asRecord(overview.data);
  const system = asRecord(ov?.system);
  const database = asRecord(ov?.database);
  const broker = asRecord(ov?.broker);
  const scheduler = asRecord(ov?.scheduler);
  const ai = asRecord(ov?.ai);
  const telegram = asRecord(ov?.telegram);
  const orders = asRecord(ov?.orders);
  const positions = asRecord(ov?.positions);
  const risk = asRecord(ov?.risk);
  const resources = asRecord(ov?.resources);
  const liveObj = asRecord(live.data);
  const readyObj = asRecord(ready.data);
  const versionObj = asRecord(version.data);

  return (
    <AdminPageShell
      title="시스템 모니터링"
      description="STEP61 · overview · health live/ready · alerts"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="상태 요약" loading={overview.isLoading}>
          <Space wrap>
            <StatusTag label="Overall" status={ov?.status} />
            <StatusTag label="Live" status={liveObj?.status} />
            <StatusTag label="Ready" status={readyObj?.status} />
            <StatusTag label="DB" status={database?.status} />
            <StatusTag label="Broker" status={broker?.status} />
            <StatusTag label="Scheduler" status={scheduler?.status} />
            <StatusTag label="AI" status={ai?.status} />
            <StatusTag label="Telegram" status={telegram?.status} />
            <StatusTag label="Risk" status={risk?.status} />
          </Space>
          {overview.error ? (
            <Typography.Text type="danger">
              {toApiError(overview.error).message}
            </Typography.Text>
          ) : null}
        </Card>

        <Card size="small" title="System Identity" loading={version.isLoading}>
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
            <Descriptions.Item label="Server">
              {cell(system?.server_status)}
            </Descriptions.Item>
            <Descriptions.Item label="Uptime(s)">
              {cell(system?.uptime_seconds ?? versionObj?.uptime_seconds)}
            </Descriptions.Item>
            <Descriptions.Item label="Environment">
              {cell(system?.environment ?? versionObj?.environment)}
            </Descriptions.Item>
            <Descriptions.Item label="Version">
              {cell(system?.version ?? versionObj?.version)}
            </Descriptions.Item>
            <Descriptions.Item label="Build">
              {cell(system?.build_version ?? versionObj?.build_version)}
            </Descriptions.Item>
            <Descriptions.Item label="Git">
              {cell(system?.git_commit ?? versionObj?.git_commit)}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}>
            <SectionCard
              title="Database"
              loading={overview.isLoading}
              error={overview.error}
              data={database}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="Broker"
              loading={overview.isLoading}
              error={overview.error}
              data={broker}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="Scheduler"
              loading={overview.isLoading}
              error={overview.error}
              data={scheduler}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="AI / Ollama"
              loading={overview.isLoading}
              error={overview.error}
              data={ai}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="Telegram"
              loading={overview.isLoading}
              error={overview.error}
              data={telegram}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="Resources"
              loading={overview.isLoading}
              error={overview.error}
              data={resources}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="Orders (today)"
              loading={overview.isLoading}
              error={overview.error}
              data={orders}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="Positions"
              loading={overview.isLoading}
              error={overview.error}
              data={positions}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="Risk"
              loading={overview.isLoading}
              error={overview.error}
              data={risk}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="Alerts (audit)"
              loading={alerts.isLoading}
              error={alerts.error}
              data={alerts.data}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="GET /health/live"
              loading={live.isLoading}
              error={live.error}
              data={live.data}
            />
          </Col>
          <Col xs={24} md={12}>
            <SectionCard
              title="GET /health/ready"
              loading={ready.isLoading}
              error={ready.error}
              data={ready.data}
            />
          </Col>
          <Col xs={24}>
            <SectionCard
              title="GET /health (상세)"
              loading={health.isLoading}
              error={health.error}
              data={health.data}
            />
          </Col>
          <Col xs={24}>
            <SectionCard
              title="GET /api/v1/monitoring/overview"
              loading={overview.isLoading}
              error={overview.error}
              data={overview.data}
            />
          </Col>
        </Row>
      </Space>
    </AdminPageShell>
  );
}
