"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Card,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";

function formatTs(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("ko-KR");
  } catch {
    return String(value);
  }
}

function lockStatusColor(status: string, stale: boolean): string {
  if (stale) return "red";
  const s = status.toUpperCase();
  if (s === "HELD") return "processing";
  if (s === "RELEASED") return "default";
  if (s === "FREE") return "green";
  return "default";
}

/** STEP 8-5-6 — Distributed Lock 상태 (강제 해제 버튼 없음) */
export function RecoveryDistributedLockPanel({
  onOpenRun,
}: {
  onOpenRun?: (runId: number) => void;
}) {
  const [autoRefresh, setAutoRefresh] = useState(true);

  const locksQuery = useQuery({
    queryKey: ["admin", "recovery-locks"],
    queryFn: () => adminApi.listAdminRecoveryLocks({ limit: 100 }),
    refetchInterval: autoRefresh ? 5000 : false,
  });

  const rows = extractRows(locksQuery.data);

  return (
    <Card
      size="small"
      title="분산 Lock (PostgreSQL)"
      extra={
        <Space>
          <Typography.Text type="secondary">자동 새로고침</Typography.Text>
          <Switch
            size="small"
            checked={autoRefresh}
            onChange={setAutoRefresh}
          />
          <Button
            size="small"
            loading={locksQuery.isFetching}
            onClick={() => void locksQuery.refetch()}
          >
            새로고침
          </Button>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
        계좌별 Lease Lock · Owner 마스킹 · Fencing Token. 강제 해제는
        제공하지 않습니다. Busy/Stale는 Lease 만료 후 Takeover됩니다.
      </Typography.Paragraph>
      <Table
        size="small"
        rowKey={(r) => String(asRecord(r)?.lock_scope_key ?? Math.random())}
        loading={locksQuery.isLoading}
        dataSource={rows}
        pagination={{ pageSize: 10 }}
        columns={[
          {
            title: "거래소/증권사",
            dataIndex: "broker_code",
            width: 90,
            render: (v) => cell(v),
          },
          {
            title: "계좌",
            key: "account",
            render: (_, row) => {
              const r = asRecord(row);
              if (r?.paper_account_id != null) {
                return `PAPER-${r.paper_account_id}`;
              }
              if (r?.user_broker_account_id != null) {
                return `UBA-${r.user_broker_account_id}`;
              }
              return cell(r?.account_kind);
            },
          },
          {
            title: "상태",
            dataIndex: "status",
            width: 120,
            render: (v, row) => {
              const r = asRecord(row);
              const stale = Boolean(r?.stale);
              const label = stale ? `${cell(v)}·STALE` : cell(v);
              return (
                <Tag color={lockStatusColor(String(v ?? ""), stale)}>
                  {label}
                </Tag>
              );
            },
          },
          {
            title: "소유자",
            dataIndex: "owner_instance_masked",
            ellipsis: true,
            render: (v) => cell(v),
          },
          {
            title: "펜스",
            dataIndex: "fencing_token",
            width: 70,
            render: (v) => cell(v),
          },
          {
            title: "획득",
            dataIndex: "acquired_at",
            render: (v) => formatTs(typeof v === "string" ? v : null),
          },
          {
            title: "하트비트",
            dataIndex: "heartbeat_at",
            render: (v) => formatTs(typeof v === "string" ? v : null),
          },
          {
            title: "만료",
            dataIndex: "lease_expires_at",
            render: (v) => formatTs(typeof v === "string" ? v : null),
          },
          {
            title: "실행",
            dataIndex: "recovery_run_id",
            width: 90,
            render: (v) => {
              const id = typeof v === "number" ? v : Number(v);
              if (!id || Number.isNaN(id)) return "-";
              return (
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  onClick={() => onOpenRun?.(id)}
                >
                  #{id}
                </Button>
              );
            },
          },
        ]}
      />
    </Card>
  );
}
