"use client";

/**
 * M4-C: /admin/upbit용 LIVE/ARM READ-only 요약.
 * mutation(LIVE/ARM/Scheduler/CRUD) 없음 — GET만.
 */

import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

function onOffTag(value: unknown, onLabel = "ON", offLabel = "OFF") {
  const on = Boolean(value);
  return <Tag color={on ? "green" : "default"}>{on ? onLabel : offLabel}</Tag>;
}

function schedulerLabel(status: Record<string, unknown> | undefined): string {
  if (!status) return "-";
  const desired = String(status.desired_state ?? status.desired ?? "").toUpperCase();
  const actual = String(status.actual_state ?? status.actual ?? "").toUpperCase();
  if (
    desired === "RUN" ||
    desired === "RUNNING" ||
    actual === "RUN" ||
    actual === "RUNNING"
  ) {
    return "RUN";
  }
  if (
    desired === "PAUSE" ||
    desired === "PAUSED" ||
    actual === "PAUSE" ||
    actual === "PAUSED" ||
    actual === "STOPPED" ||
    desired === ""
  ) {
    return "PAUSE";
  }
  return `${desired || "-"}/${actual || "-"}`;
}

export function UpbitLiveStatusReadSummary() {
  const accountsQuery = useQuery({
    queryKey: ["admin", "broker-accounts", "UPBIT", "read-summary"],
    queryFn: () =>
      adminApi.listAdminBrokerAccounts({
        broker_code: "UPBIT",
        include_inactive: true,
        limit: 100,
      }),
  });

  const readinessQuery = useQuery({
    queryKey: ["admin", "live-ops-readiness", "read-summary"],
    queryFn: adminApi.getAdminLiveOpsReadiness,
  });

  const schedulerQuery = useQuery({
    queryKey: ["admin", "trading-scheduler", "status", "read-summary"],
    queryFn: adminApi.getTradingSchedulerStatus,
  });

  const rows = extractRows(accountsQuery.data) as Record<string, unknown>[];
  const readiness = readinessQuery.data as
    | {
        dry_run_ready?: boolean;
        blockers?: string[];
      }
    | undefined;
  const schedulerStatus = schedulerQuery.data as
    | Record<string, unknown>
    | undefined;

  return (
    <Card
      size="small"
      title="UPBIT LIVE 상태 (조회 전용)"
      extra={
        <Space wrap>
          <Link href={adminRoutes.accounts}>계좌 관리 (LIVE/ARM 제어)</Link>
          <Link href={adminRoutes.recovery}>장애 복구</Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="UPBIT 자동매매 운영 상태를 조회합니다."
          description="계좌 설정 및 LIVE/ARM/Trading Scheduler 제어는 계좌 관리에서 수행합니다. UBA CRUD·Credential·Resume도 계좌 관리 화면입니다."
        />

        <Space wrap>
          <Typography.Text type="secondary">Live-ops readiness:</Typography.Text>
          {readinessQuery.isLoading ? (
            <Tag>로딩</Tag>
          ) : readinessQuery.error ? (
            <Tag color="red">{toApiError(readinessQuery.error).message}</Tag>
          ) : (
            <Tag color={readiness?.dry_run_ready ? "green" : "orange"}>
              {readiness?.dry_run_ready ? "OK" : "BLOCKED"}
            </Tag>
          )}
          <Typography.Text type="secondary">Trading Scheduler:</Typography.Text>
          {schedulerQuery.isLoading ? (
            <Tag>로딩</Tag>
          ) : (
            <Tag>{schedulerLabel(schedulerStatus)}</Tag>
          )}
        </Space>

        {(readiness?.blockers ?? []).length > 0 ? (
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            blockers: {(readiness?.blockers ?? []).join(", ")}
          </Typography.Text>
        ) : null}

        <Table
          size="small"
          pagination={false}
          loading={accountsQuery.isLoading}
          rowKey={(row) =>
            String(row.user_broker_account_id ?? row.id ?? JSON.stringify(row))
          }
          locale={{
            emptyText: accountsQuery.error
              ? toApiError(accountsQuery.error).message
              : "UPBIT UBA 없음",
          }}
          columns={[
            {
              title: "UBA",
              dataIndex: "user_broker_account_id",
              width: 80,
              render: (v: unknown, row: Record<string, unknown>) =>
                cell(v ?? row.id),
            },
            {
              title: "alias",
              dataIndex: "account_alias",
              ellipsis: true,
              render: (v: unknown) => cell(v),
            },
            {
              title: "Credential",
              key: "credential",
              width: 100,
              render: (_: unknown, row: Record<string, unknown>) => {
                const cred = row.credential as
                  | { registered?: boolean; status?: string }
                  | undefined;
                const registered = Boolean(cred?.registered);
                return (
                  <Tag color={registered ? "green" : "default"}>
                    {registered
                      ? "등록"
                      : cell(cred?.status ?? row.credential_status) || "미등록"}
                  </Tag>
                );
              },
            },
            {
              title: "LIVE",
              key: "live",
              width: 80,
              render: (_: unknown, row: Record<string, unknown>) =>
                onOffTag(row.live_order_enabled),
            },
            {
              title: "ARM",
              key: "arm",
              width: 80,
              render: (_: unknown, row: Record<string, unknown>) =>
                onOffTag(row.live_armed),
            },
            {
              title: "Paused",
              key: "paused",
              width: 90,
              render: (_: unknown, row: Record<string, unknown>) =>
                onOffTag(row.trading_paused, "YES", "NO"),
            },
          ]}
          dataSource={rows}
        />
      </Space>
    </Card>
  );
}
