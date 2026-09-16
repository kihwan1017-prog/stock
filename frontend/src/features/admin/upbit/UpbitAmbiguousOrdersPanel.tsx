"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

const STATUS_COLOR: Record<string, string> = {
  AMBIGUOUS_SUBMISSION: "orange",
  REMOTE_LOOKUP_PENDING: "gold",
  IDENTITY_CONFLICT: "red",
  MANUAL_REVIEW_REQUIRED: "magenta",
};

function formatTs(value: unknown): string {
  if (!value) return "-";
  try {
    return new Date(String(value)).toLocaleString("ko-KR");
  } catch {
    return String(value);
  }
}

/** STEP 8-5-12 — Upbit Ambiguous 주문 패널 */
export function UpbitAmbiguousOrdersPanel() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const listQuery = useQuery({
    queryKey: ["admin", "upbit-ambiguous-orders"],
    queryFn: () => adminApi.listUpbitAmbiguousOrders({ limit: 100 }),
  });

  const healthQuery = useQuery({
    queryKey: ["admin", "upbit-ambiguous-health"],
    queryFn: () => adminApi.getUpbitAmbiguousHealth(),
  });

  // STEP 8-5-14 — Resolver Scheduler 상태 / 실행 이력
  const resolverStatusQuery = useQuery({
    queryKey: ["admin", "upbit-ambiguous-resolver-status"],
    queryFn: () => adminApi.getUpbitAmbiguousResolverStatus(),
    refetchInterval: 15000,
  });

  const resolverRunsQuery = useQuery({
    queryKey: ["admin", "upbit-ambiguous-resolver-runs"],
    queryFn: () => adminApi.listUpbitAmbiguousResolverRuns({ limit: 20 }),
  });

  const invalidateAll = () => {
    void qc.invalidateQueries({
      queryKey: ["admin", "upbit-ambiguous-orders"],
    });
    void qc.invalidateQueries({
      queryKey: ["admin", "upbit-ambiguous-health"],
    });
    void qc.invalidateQueries({
      queryKey: ["admin", "upbit-ambiguous-resolver-status"],
    });
    void qc.invalidateQueries({
      queryKey: ["admin", "upbit-ambiguous-resolver-runs"],
    });
  };

  const runNowMut = useMutation({
    mutationFn: () => adminApi.runUpbitAmbiguousResolverNow(),
    onSuccess: (result) => {
      const r = asRecord(result);
      message.success(
        `Resolver 즉시 실행: ${String(r?.status ?? "OK")} (claimed=${cell(r?.claimed_count)})`,
      );
      invalidateAll();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const retryLookupMut = useMutation({
    mutationFn: (orderId: number) =>
      adminApi.retryUpbitAmbiguousLookup(orderId),
    onSuccess: () => {
      message.success("Claim 경로로 재조회 완료");
      invalidateAll();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const releaseStaleClaimMut = useMutation({
    mutationFn: (orderId: number) =>
      adminApi.releaseUpbitAmbiguousStaleClaim(orderId),
    onSuccess: () => {
      message.success("만료된 Claim을 해제했습니다");
      invalidateAll();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const lookupMut = useMutation({
    mutationFn: (orderId: number) =>
      adminApi.lookupUpbitAmbiguousOrder(orderId),
    onSuccess: () => {
      message.success("원격 조회 완료");
      void qc.invalidateQueries({
        queryKey: ["admin", "upbit-ambiguous-orders"],
      });
      void qc.invalidateQueries({
        queryKey: ["admin", "upbit-ambiguous-health"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const manualMut = useMutation({
    mutationFn: (orderId: number) =>
      adminApi.markUpbitAmbiguousManualReview(
        orderId,
        "admin marked manual review",
      ),
    onSuccess: () => {
      message.success("Manual Review로 전환");
      void qc.invalidateQueries({
        queryKey: ["admin", "upbit-ambiguous-orders"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const approveMut = useMutation({
    mutationFn: (orderId: number) =>
      adminApi.approveUpbitAmbiguousResubmit(
        orderId,
        "admin approved resubmit prep",
      ),
    onSuccess: () => {
      message.success("재제출 준비(새 Identifier) — 자동 전송 없음");
      void qc.invalidateQueries({
        queryKey: ["admin", "upbit-ambiguous-orders"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rejectMut = useMutation({
    mutationFn: (orderId: number) =>
      adminApi.rejectUpbitAmbiguousResubmit(
        orderId,
        "admin rejected resubmit",
      ),
    onSuccess: () => {
      message.success("재제출 거절");
      void qc.invalidateQueries({
        queryKey: ["admin", "upbit-ambiguous-orders"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rows = extractRows(listQuery.data);
  const health = asRecord(healthQuery.data);
  const resolverStatus = asRecord(resolverStatusQuery.data);
  const scheduler = asRecord(resolverStatus?.scheduler);
  const lastRun = asRecord(resolverStatus?.last_run);
  const runRows = extractRows(resolverRunsQuery.data);
  const busy =
    lookupMut.isPending ||
    manualMut.isPending ||
    approveMut.isPending ||
    rejectMut.isPending ||
    retryLookupMut.isPending ||
    releaseStaleClaimMut.isPending;

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size="middle">
      <Typography.Text type="secondary">
        ambiguous={cell(health?.ambiguous_count)} / lookup_pending=
        {cell(health?.lookup_pending_count)} / conflict=
        {cell(health?.identity_conflict_count)} / manual=
        {cell(health?.manual_review_count)} / oldest=
        {cell(health?.oldest_ambiguous_since)}
      </Typography.Text>

      <Card
        size="small"
        title="Resolver Scheduler (원격 조회 전용 — 자동 재제출 없음)"
        extra={
          <Space>
            <Tag color={scheduler?.running ? "green" : "default"}>
              {scheduler?.running ? "Running" : "Stopped"}
            </Tag>
            <Button
              size="small"
              type="primary"
              loading={runNowMut.isPending}
              onClick={() => runNowMut.mutate()}
            >
              지금 실행
            </Button>
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          DB Claim + 계좌 단위 분산 Lock 기반. Poll=
          {cell(resolverStatus?.poll_seconds)}s / Batch=
          {cell(resolverStatus?.batch_size)} / Claim=
          {cell(resolverStatus?.claim_seconds)}s / 계좌당 최대=
          {cell(resolverStatus?.max_orders_per_account_per_run)} / 다음 실행=
          {formatTs(scheduler?.next_run_at)}
        </Typography.Paragraph>
        <Typography.Text type="secondary">
          최근 실행: {cell(lastRun?.status_code)} (claimed=
          {cell(lastRun?.claimed_count)}, found={cell(lastRun?.found_count)},
          not_found={cell(lastRun?.not_found_count)}, manual=
          {cell(lastRun?.manual_review_count)}, error=
          {cell(lastRun?.error_count)}) @ {formatTs(lastRun?.started_at)}
        </Typography.Text>
      </Card>

      <Table
        size="small"
        loading={listQuery.isLoading}
        rowKey={(r) => String(asRecord(r)?.order_id ?? Math.random())}
        dataSource={rows}
        pagination={{ pageSize: 10 }}
        columns={[
          {
            title: "주문",
            dataIndex: "order_id",
            width: 80,
            render: (v) => cell(v),
          },
          {
            title: "Identifier",
            dataIndex: "client_order_identifier",
            render: (v) => cell(v),
          },
          {
            title: "종목",
            dataIndex: "symbol",
            width: 100,
            render: (v) => cell(v),
          },
          {
            title: "매수/매도",
            dataIndex: "side_code",
            width: 70,
            render: (v) => cell(v),
          },
          {
            title: "상태",
            dataIndex: "status_code",
            render: (v) => (
              <Tag color={STATUS_COLOR[String(v)] ?? "default"}>
                {cell(v)}
              </Tag>
            ),
          },
          {
            title: "Lookup",
            dataIndex: "remote_lookup_status",
            render: (v) => cell(v),
          },
          {
            title: "Attempts",
            dataIndex: "remote_lookup_attempt_count",
            width: 80,
            render: (v) => cell(v),
          },
          {
            title: "Next Lookup",
            dataIndex: "next_remote_lookup_at",
            render: (v) => cell(v),
          },
          {
            title: "UUID",
            dataIndex: "broker_order_id",
            render: (v) => cell(v),
          },
          {
            title: "Claim",
            key: "claim",
            render: (_, row) => {
              const r = asRecord(row);
              if (!r?.resolver_claimed_by) return "-";
              return (
                <Typography.Text style={{ fontSize: 12 }}>
                  {cell(r.resolver_claimed_by)}
                  <br />
                  만료: {formatTs(r.resolver_claim_expires_at)}
                </Typography.Text>
              );
            },
          },
          {
            title: "작업",
            key: "actions",
            render: (_, row) => {
              const r = asRecord(row);
              const id = Number(r?.order_id);
              return (
                <Space wrap>
                  <Button
                    size="small"
                    disabled={busy || !Number.isFinite(id)}
                    loading={lookupMut.isPending}
                    onClick={() => lookupMut.mutate(id)}
                  >
                    Lookup
                  </Button>
                  <Button
                    size="small"
                    disabled={busy || !Number.isFinite(id)}
                    loading={retryLookupMut.isPending}
                    onClick={() => retryLookupMut.mutate(id)}
                  >
                    재조회(Claim)
                  </Button>
                  {r?.resolver_claimed_by ? (
                    <Button
                      size="small"
                      disabled={busy || !Number.isFinite(id)}
                      loading={releaseStaleClaimMut.isPending}
                      onClick={() =>
                        Modal.confirm({
                          title: "만료된 Claim 강제 해제",
                          content:
                            "유효한 Claim은 거부됩니다. 만료된 경우에만 해제됩니다.",
                          onOk: () => releaseStaleClaimMut.mutateAsync(id),
                        })
                      }
                    >
                      Claim 해제
                    </Button>
                  ) : null}
                  <Button
                    size="small"
                    disabled={busy}
                    onClick={() =>
                      Modal.confirm({
                        title: "Manual Review 전환",
                        onOk: () => manualMut.mutateAsync(id),
                      })
                    }
                  >
                    Manual
                  </Button>
                  <Button
                    size="small"
                    danger
                    disabled={busy}
                    onClick={() =>
                      Modal.confirm({
                        title: "재제출 승인 (새 Identifier)",
                        content:
                          "자동 전송하지 않습니다. 새 Generation/Identifier만 준비합니다.",
                        okType: "danger",
                        onOk: () => approveMut.mutateAsync(id),
                      })
                    }
                  >
                    재제출 승인
                  </Button>
                  <Button
                    size="small"
                    disabled={busy}
                    onClick={() =>
                      Modal.confirm({
                        title: "재제출 거절",
                        onOk: () => rejectMut.mutateAsync(id),
                      })
                    }
                  >
                    거절
                  </Button>
                </Space>
              );
            },
          },
        ]}
      />

      <Typography.Title level={5} style={{ marginTop: 8 }}>
        Resolver 실행 이력
      </Typography.Title>
      <Table
        size="small"
        loading={resolverRunsQuery.isLoading}
        rowKey={(r) => String(asRecord(r)?.run_id ?? Math.random())}
        dataSource={runRows}
        pagination={{ pageSize: 10 }}
        columns={[
          {
            title: "ID",
            dataIndex: "run_id",
            width: 70,
            render: (v) => cell(v),
          },
          {
            title: "Trigger",
            dataIndex: "trigger_type",
            width: 110,
            render: (v) => cell(v),
          },
          {
            title: "상태",
            dataIndex: "status_code",
            width: 90,
            render: (v) => (
              <Tag
                color={
                  v === "SUCCEEDED"
                    ? "green"
                    : v === "PARTIAL"
                      ? "gold"
                      : v === "FAILED"
                        ? "red"
                        : "blue"
                }
              >
                {cell(v)}
              </Tag>
            ),
          },
          {
            title: "Due",
            dataIndex: "due_count",
            width: 60,
            render: (v) => cell(v),
          },
          {
            title: "Claimed",
            dataIndex: "claimed_count",
            width: 70,
            render: (v) => cell(v),
          },
          {
            title: "Found",
            dataIndex: "found_count",
            width: 70,
            render: (v) => cell(v),
          },
          {
            title: "NotFound",
            dataIndex: "not_found_count",
            width: 80,
            render: (v) => cell(v),
          },
          {
            title: "Manual",
            dataIndex: "manual_review_count",
            width: 70,
            render: (v) => cell(v),
          },
          {
            title: "LockBusy",
            dataIndex: "lock_busy_count",
            width: 80,
            render: (v) => cell(v),
          },
          {
            title: "Error",
            dataIndex: "error_count",
            width: 60,
            render: (v) => cell(v),
          },
          {
            title: "시작",
            dataIndex: "started_at",
            render: (v) => formatTs(v),
          },
          {
            title: "소요(ms)",
            dataIndex: "duration_ms",
            width: 90,
            render: (v) => cell(v),
          },
        ]}
      />
    </Space>
  );
}
