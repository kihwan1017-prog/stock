"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Descriptions,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminDbPage() {
  const [schema, setSchema] = useState("trading");

  const status = useQuery({
    queryKey: queryKeys.admin.opsDbStatus(),
    queryFn: adminApi.getOpsDbStatus,
  });
  const migration = useQuery({
    queryKey: queryKeys.admin.opsMigration(),
    queryFn: adminApi.getOpsMigrationStatus,
  });
  const backup = useQuery({
    queryKey: queryKeys.admin.opsBackup(),
    queryFn: adminApi.getOpsBackupStatus,
  });
  const tables = useQuery({
    queryKey: queryKeys.admin.opsTables(schema),
    queryFn: () => adminApi.listOpsDbTables(schema),
  });

  const statusObj = asRecord(status.data);
  const migrationObj = asRecord(migration.data);
  const backupObj = asRecord(backup.data);
  const dbObj = asRecord(statusObj?.database);
  const schemaRows = extractRows(statusObj?.schemas).length
    ? extractRows(statusObj?.schemas)
    : Array.isArray(statusObj?.schemas)
      ? (statusObj?.schemas as Record<string, unknown>[])
      : [];

  return (
    <AdminPageShell
      title="DB 관리"
      description="상태 · Migration · Backup 도구 점검 (읽기 전용)"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="SQL 콘솔·웹 migrate·웹 restore는 제공하지 않습니다."
          description="구조 변경은 `python -m alembic upgrade head`, 백업/복구는 docs/manual/백업복구매뉴얼.md 의 pg_dump/pg_restore를 사용하세요."
        />

        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <Card size="small" loading={status.isLoading} title="DB 상태">
              {status.error ? (
                <Typography.Text type="danger">
                  {toApiError(status.error).message}
                </Typography.Text>
              ) : (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="연결">
                    <Tag
                      color={
                        String(statusObj?.status).toUpperCase() === "UP"
                          ? "success"
                          : "error"
                      }
                    >
                      {cell(statusObj?.status)}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="host">
                    {cell(dbObj?.host)}:{cell(dbObj?.port)}
                  </Descriptions.Item>
                  <Descriptions.Item label="database">
                    {cell(dbObj?.name)}
                  </Descriptions.Item>
                  <Descriptions.Item label="user">
                    {cell(dbObj?.user)}
                  </Descriptions.Item>
                </Descriptions>
              )}
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" loading={migration.isLoading} title="Migration 상태">
              {migration.error ? (
                <Typography.Text type="danger">
                  {toApiError(migration.error).message}
                </Typography.Text>
              ) : (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="current">
                    <Typography.Text code>
                      {cell(migrationObj?.current)}
                    </Typography.Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="heads">
                    <Typography.Text code>
                      {cell(migrationObj?.heads)}
                    </Typography.Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="동기화">
                    <Tag color={migrationObj?.in_sync ? "success" : "warning"}>
                      {migrationObj?.in_sync ? "IN SYNC" : "DRIFT"}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="CLI">
                    <Typography.Text code>
                      {cell(migrationObj?.upgrade_command)}
                    </Typography.Text>
                  </Descriptions.Item>
                </Descriptions>
              )}
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" loading={backup.isLoading} title="Backup / Restore">
              {backup.error ? (
                <Typography.Text type="danger">
                  {toApiError(backup.error).message}
                </Typography.Text>
              ) : (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="도구">
                    <Tag color={backupObj?.tools_ready ? "success" : "warning"}>
                      {backupObj?.tools_ready ? "READY" : "MISSING"}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="pg_dump">
                    {cell(backupObj?.pg_dump_path ?? "—")}
                  </Descriptions.Item>
                  <Descriptions.Item label="version">
                    {cell(backupObj?.pg_dump_version ?? "—")}
                  </Descriptions.Item>
                  <Descriptions.Item label="백업 폴더">
                    {cell(backupObj?.recommended_backup_dir)}
                  </Descriptions.Item>
                  <Descriptions.Item label="매뉴얼">
                    {cell(backupObj?.manual)}
                  </Descriptions.Item>
                </Descriptions>
              )}
              <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                {cell(backupObj?.restore_note)}
              </Typography.Paragraph>
            </Card>
          </Col>
        </Row>

        <AdminDataTable
          title="스키마별 테이블 수"
          loading={status.isLoading}
          error={status.error ? toApiError(status.error) : null}
          rowKey={(r) => cell(r.table_schema)}
          columns={[
            { title: "schema", dataIndex: "table_schema" },
            { title: "tables", dataIndex: "table_count" },
          ]}
          dataSource={schemaRows}
        />

        <Card
          size="small"
          title="테이블 목록"
          extra={
            <Select
              value={schema}
              style={{ width: 160 }}
              onChange={setSchema}
              options={[
                "trading",
                "operation",
                "market",
                "auth",
                "broker",
                "strategy",
                "disclosure",
                "news",
                "ai",
                "backtest",
              ].map((value) => ({ value, label: value }))}
            />
          }
        >
          <AdminDataTable
            title={`GET /ops/db/tables?schema=${schema}`}
            loading={tables.isLoading}
            error={tables.error ? toApiError(tables.error) : null}
            rowKey={(r) => cell(r.table_name ?? r)}
            columns={[{ title: "table", dataIndex: "table_name" }]}
            dataSource={(
              (asRecord(tables.data)?.tables as string[] | undefined) ?? []
            ).map((name) => ({ table_name: name }))}
          />
        </Card>

        <AdminJsonCard
          title="Backup 예시 명령"
          data={{
            example_command: backupObj?.example_command,
            restore_note: backupObj?.restore_note,
          }}
        />
      </Space>
    </AdminPageShell>
  );
}
