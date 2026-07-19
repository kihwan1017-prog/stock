"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";

import * as adminApi from "@/features/admin/api/adminApi";
import { UnimplementedApiPanel } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { OPERATION_CENTER_TILES } from "@/features/admin/operations/operationCenterTiles";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { adminRoutes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function statusTag(label: string, status: unknown) {
  const normalized = String(status ?? "UNKNOWN").toUpperCase();
  const color =
    normalized === "UP" ||
    normalized === "OK" ||
    normalized === "HEALTHY" ||
    normalized === "CONFIGURED" ||
    normalized === "TRUE" ||
    normalized === "IN_SYNC"
      ? "success"
      : normalized === "DOWN" ||
          normalized === "ERROR" ||
          normalized === "FAILED" ||
          normalized === "FALSE"
        ? "error"
        : "warning";
  return (
    <Tag color={color}>
      {label}: {normalized}
    </Tag>
  );
}

function supportColor(support: "live" | "partial" | "planned") {
  if (support === "live") return "success";
  if (support === "partial") return "processing";
  return "default";
}

export default function AdminOperationCenterPage() {
  const healthQuery = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: adminApi.getHealth,
    refetchInterval: 15_000,
  });

  const versionQuery = useQuery({
    queryKey: queryKeys.system.version(),
    queryFn: adminApi.getVersion,
  });

  const dbQuery = useQuery({
    queryKey: queryKeys.admin.opsDbStatus(),
    queryFn: adminApi.getOpsDbStatus,
    retry: false,
  });

  const migrationQuery = useQuery({
    queryKey: queryKeys.admin.opsMigration(),
    queryFn: adminApi.getOpsMigrationStatus,
    retry: false,
  });

  const backupQuery = useQuery({
    queryKey: queryKeys.admin.opsBackup(),
    queryFn: adminApi.getOpsBackupStatus,
    retry: false,
  });

  const jobsQuery = useQuery({
    queryKey: queryKeys.admin.jobs(),
    queryFn: adminApi.listJobs,
    retry: false,
  });

  const jobHistoryQuery = useQuery({
    queryKey: queryKeys.admin.jobHistory(),
    queryFn: () => adminApi.listJobHistory({ limit: 5 }),
    retry: false,
  });

  const brokerQuery = useQuery({
    queryKey: queryKeys.admin.brokerAccount(),
    queryFn: adminApi.getBrokerAccount,
    retry: false,
  });

  const kiwoomQuery = useQuery({
    queryKey: queryKeys.admin.kiwoomConfig(),
    queryFn: adminApi.getKiwoomConfiguration,
    retry: false,
  });

  const auditQuery = useQuery({
    queryKey: queryKeys.admin.auditEvents({ limit: 5 }),
    queryFn: () => adminApi.listAuditEvents({ limit: 5 }),
    retry: false,
  });

  const health = asRecord(healthQuery.data);
  const components = asRecord(health?.components) ?? {};
  const version = asRecord(versionQuery.data);
  const db = asRecord(dbQuery.data);
  const migration = asRecord(migrationQuery.data);
  const backup = asRecord(backupQuery.data);
  const broker = asRecord(brokerQuery.data);
  const kiwoom = asRecord(kiwoomQuery.data);
  const jobRows = extractRows(jobsQuery.data);
  const historyRows = extractRows(jobHistoryQuery.data).slice(0, 5);
  const auditRows = extractRows(auditQuery.data).slice(0, 5);

  return (
    <AdminPageShell
      title="운영센터"
      description="Scheduler · Broker · PostgreSQL · Monitor · Batch · Env · Logs · Backup · Health"
      extra={
        <Space wrap>
          <Link href={adminRoutes.monitoring}>모니터링</Link>
          <Link href={adminRoutes.scheduler}>Scheduler</Link>
          <Link href={adminRoutes.db}>DB</Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="Admin 전용 운영 허브"
          description="상세 작업은 각 전용 화면에서 수행합니다. 웹 Backup dump / Restore / 앱 로그 테일은 Backend 미구현입니다."
        />

        <Card size="small" title="Health Check" loading={healthQuery.isLoading}>
          {healthQuery.error ? (
            <Alert
              type="error"
              showIcon
              title={toApiError(healthQuery.error).message}
            />
          ) : (
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Space wrap>
                {statusTag("Overall", health?.status)}
                {statusTag(
                  "DB",
                  asRecord(components.database)?.status ?? db?.status,
                )}
                {statusTag(
                  "Scheduler",
                  asRecord(components.scheduler)?.status,
                )}
                {statusTag(
                  "Kiwoom",
                  asRecord(components.kiwoom_rest)?.status,
                )}
                <Tag>
                  version: {cell(version?.version ?? version?.app_version)}
                </Tag>
              </Space>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                GET /health · GET /version
              </Typography.Text>
            </Space>
          )}
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={8}>
            <Card
              size="small"
              title="PostgreSQL"
              loading={dbQuery.isLoading || migrationQuery.isLoading}
              extra={<Link href={adminRoutes.db}>상세</Link>}
            >
              {dbQuery.error || migrationQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(
                    dbQuery.error ?? migrationQuery.error,
                  ).message}
                />
              ) : (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="DB">
                    {cell(db?.status ?? db?.database)}
                  </Descriptions.Item>
                  <Descriptions.Item label="Migration">
                    <Tag color={migration?.in_sync ? "success" : "warning"}>
                      {migration?.in_sync ? "IN SYNC" : "DRIFT"}
                    </Tag>{" "}
                    {cell(migration?.current)}
                  </Descriptions.Item>
                </Descriptions>
              )}
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card
              size="small"
              title="Backup · Restore"
              loading={backupQuery.isLoading}
              extra={<Link href={adminRoutes.db}>DB 관리</Link>}
            >
              {backupQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(backupQuery.error).message}
                  description="ops:execute 권한이 필요할 수 있습니다."
                />
              ) : (
                <Descriptions column={1} size="small">
                  {Object.entries(backup ?? {})
                    .slice(0, 6)
                    .map(([key, value]) => (
                      <Descriptions.Item key={key} label={key}>
                        {cell(value)}
                      </Descriptions.Item>
                    ))}
                </Descriptions>
              )}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                GET /ops/backup/status — 웹 dump/restore 없음
              </Typography.Text>
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card
              size="small"
              title="Broker"
              loading={brokerQuery.isLoading || kiwoomQuery.isLoading}
              extra={
                <Space>
                  <Link href={adminRoutes.kiwoom}>키움</Link>
                  <Link href={adminRoutes.upbit}>업비트</Link>
                </Space>
              }
            >
              {brokerQuery.error && kiwoomQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title="브로커 상태 조회 실패"
                  description={toApiError(
                    brokerQuery.error ?? kiwoomQuery.error,
                  ).message}
                />
              ) : (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="Kiwoom">
                    {cell(
                      kiwoom?.environment ??
                        kiwoom?.mode ??
                        kiwoom?.status ??
                        "-",
                    )}
                  </Descriptions.Item>
                  <Descriptions.Item label="Account">
                    {cell(
                      broker?.account_no ??
                        broker?.account_id ??
                        broker?.status ??
                        "-",
                    )}
                  </Descriptions.Item>
                </Descriptions>
              )}
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card
              size="small"
              title={`Scheduler · Jobs (${jobRows.length})`}
              loading={jobsQuery.isLoading}
              extra={<Link href={adminRoutes.scheduler}>Scheduler</Link>}
            >
              {jobsQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(jobsQuery.error).message}
                />
              ) : (
                <Space wrap>
                  {jobRows.slice(0, 12).map((row, index) => (
                    <Tag key={`${cell(row.name ?? row.job_name)}-${index}`}>
                      {cell(row.name ?? row.job_name ?? row.id)}
                    </Tag>
                  ))}
                  {jobRows.length === 0 ? (
                    <Typography.Text type="secondary">잡 없음</Typography.Text>
                  ) : null}
                </Space>
              )}
              {historyRows.length > 0 ? (
                <Typography.Paragraph
                  type="secondary"
                  style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}
                >
                  최근 실행:{" "}
                  {historyRows
                    .map((row) =>
                      cell(row.job_name ?? row.name ?? row.status),
                    )
                    .join(" · ")}
                </Typography.Paragraph>
              ) : null}
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card
              size="small"
              title="Log Viewer (감사)"
              loading={auditQuery.isLoading}
              extra={<Link href={adminRoutes.logs}>로그</Link>}
            >
              {auditQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(auditQuery.error).message}
                />
              ) : auditRows.length === 0 ? (
                <Typography.Text type="secondary">최근 감사 이벤트 없음</Typography.Text>
              ) : (
                <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                  {auditRows.map((row, index) => (
                    <Typography.Text
                      key={`${cell(row.event_id ?? row.id)}-${index}`}
                      style={{ fontSize: 12 }}
                    >
                      {cell(row.event_type ?? row.action)} ·{" "}
                      {cell(row.created_at ?? row.occurred_at)}
                    </Typography.Text>
                  ))}
                </Space>
              )}
            </Card>
          </Col>
        </Row>

        <Card size="small" title="운영 기능 바로가기">
          <Row gutter={[12, 12]}>
            {OPERATION_CENTER_TILES.map((tile) => (
              <Col xs={24} sm={12} md={8} lg={6} key={tile.id}>
                <Card
                  size="small"
                  type="inner"
                  title={
                    <Space>
                      <span>{tile.title}</span>
                      <Tag color={supportColor(tile.support)}>
                        {tile.support}
                      </Tag>
                    </Space>
                  }
                  actions={[
                    <Link key="go" href={tile.href}>
                      <Button type="link" size="small">
                        열기
                      </Button>
                    </Link>,
                  ]}
                >
                  <Typography.Paragraph
                    type="secondary"
                    style={{ minHeight: 40, marginBottom: 8 }}
                  >
                    {tile.description}
                  </Typography.Paragraph>
                  <Typography.Text style={{ fontSize: 11 }} type="secondary">
                    {tile.apis.slice(0, 2).join(" · ")}
                  </Typography.Text>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <Card size="small" title="Batch · Environment">
              <Space wrap>
                <Link href={adminRoutes.batch}>
                  <Button>Batch</Button>
                </Link>
                <Link href={adminRoutes.envSettings}>
                  <Button>Environment</Button>
                </Link>
                <Link href={adminRoutes.systemSettings}>
                  <Button>System Settings</Button>
                </Link>
                <Link href={adminRoutes.monitoring}>
                  <Button type="primary">System Monitor</Button>
                </Link>
              </Space>
            </Card>
          </Col>
          <Col xs={24} md={16}>
            <UnimplementedApiPanel
              feature="웹 Backup dump / Restore · 앱 로그 테일"
              reason="운영센터는 도구 점검·감사 로그·CLI 안내까지 제공합니다. 웹에서 dump/restore 실행과 앱 로그 파일 테일링 API는 없습니다."
              expectedApis={[
                "POST /api/v1/ops/backup/dump",
                "POST /api/v1/ops/backup/restore",
                "GET /api/v1/ops/logs/tail",
              ]}
              relatedApis={[
                "GET /api/v1/ops/backup/status",
                "GET /api/v1/audit/events",
                "docs/manual/백업복구매뉴얼.md",
              ]}
              showShell={false}
            />
          </Col>
        </Row>
      </Space>
    </AdminPageShell>
  );
}
