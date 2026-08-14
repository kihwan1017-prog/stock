"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, InputNumber, Space, Typography } from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { UpbitAmbiguousOrdersPanel } from "@/features/admin/upbit/UpbitAmbiguousOrdersPanel";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/**
 * M5-A: page-level broker ops + Ambiguous를「운영·정합」탭으로 이동.
 * mutation/API 시그니처는 기존 page.tsx와 동일 (로직 변경 없음).
 * 탭 첫 방문 시에만 mount → Overview에서 rate/snapshot GET 방지.
 */
export function UpbitHubOpsSection() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [ubaId, setUbaId] = useState<number | null>(null);

  const accountStatus = useQuery({
    queryKey: queryKeys.admin.upbitAccountStatus(),
    queryFn: adminApi.getUpbitAccountStatus,
  });

  const accountSnapshot = useQuery({
    queryKey: [...queryKeys.admin.upbitAccountSnapshot(), ubaId],
    queryFn: () => adminApi.getUpbitAccountSnapshot(ubaId as number),
    enabled: ubaId != null,
    retry: false,
  });

  const connectionTest = useMutation({
    mutationFn: adminApi.testUpbitAccountConnection,
    onSuccess: (data) => {
      const mode =
        data && typeof data === "object" && "mode" in data
          ? String((data as { mode?: string }).mode ?? "")
          : "";
      message.success(
        mode === "mock"
          ? "연결 테스트 성공 (mock)"
          : "연결 테스트 성공",
      );
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitAccountStatus(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const syncAccount = useMutation({
    mutationFn: (id: number) => adminApi.syncUpbitAccount(id),
    onSuccess: () => {
      message.success("업비트 잔고 스냅샷 동기화 완료 (UBA Binding)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitAccountSnapshot(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitAccountStatus(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const reconcileOrders = useMutation({
    mutationFn: adminApi.reconcileUpbitOrders,
    onSuccess: () => {
      message.success("업비트 주문 체결 동기화 요청 완료");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rateLimits = useQuery({
    queryKey: queryKeys.admin.upbitRateLimits(),
    queryFn: () => adminApi.getUpbitRateLimits({ limit: 100 }),
  });

  const recheckRateLimit = useMutation({
    mutationFn: (targetUbaId: number) =>
      adminApi.recheckUpbitRateLimits(targetUbaId),
    onSuccess: () => {
      message.success("Rate Limit 상태 재조회 완료 (강제 해제 없음)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitRateLimits(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const snapshotPositions =
    accountSnapshot.data &&
    typeof accountSnapshot.data === "object" &&
    "positions" in accountSnapshot.data &&
    Array.isArray((accountSnapshot.data as { positions?: unknown }).positions)
      ? ((accountSnapshot.data as { positions: Record<string, unknown>[] })
          .positions)
      : [];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        연결 테스트·잔고/체결 동기화·Rate Limit·Ambiguous 정합입니다. LIVE/ARM
        제어는 계좌 관리에서 수행합니다.
      </Typography.Paragraph>

      <Space wrap>
        <InputNumber
          placeholder="UBA ID"
          min={1}
          value={ubaId ?? undefined}
          onChange={(v) => setUbaId(typeof v === "number" ? v : null)}
        />
        <Button
          loading={connectionTest.isPending}
          onClick={() => connectionTest.mutate()}
        >
          연결 테스트
        </Button>
        <Button
          loading={syncAccount.isPending}
          disabled={ubaId == null}
          onClick={() => ubaId != null && syncAccount.mutate(ubaId)}
        >
          잔고 동기화
        </Button>
        <Button
          loading={reconcileOrders.isPending}
          onClick={() => reconcileOrders.mutate()}
        >
          체결 동기화
        </Button>
      </Space>

      <AdminJsonCard
        title="GET /broker/upbit/account/status"
        loading={accountStatus.isLoading}
        error={
          accountStatus.error ? toApiError(accountStatus.error) : null
        }
        data={accountStatus.data}
      />

      <AdminDataTable
        title="Upbit Rate Limit (STEP 8-5-8)"
        loading={rateLimits.isLoading}
        error={rateLimits.error ? toApiError(rateLimits.error) : null}
        rowKey={(r) =>
          cell(
            r.id ??
              `${r.user_broker_account_id}-${r.endpoint_group}`,
          )
        }
        columns={[
          { title: "user", dataIndex: "user_id", width: 80 },
          { title: "계좌", dataIndex: "account_masked", width: 120 },
          { title: "Group", dataIndex: "endpoint_group", width: 100 },
          { title: "상태", dataIndex: "status", width: 110 },
          {
            title: "Rem Sec",
            dataIndex: "remaining_second",
            width: 90,
          },
          {
            title: "Retry-After",
            dataIndex: "last_retry_after_seconds",
            width: 100,
          },
          { title: "Cooldown", dataIndex: "cooldown_until" },
          { title: "418 Block", dataIndex: "blocked_until" },
          {
            title: "HTTP",
            dataIndex: "last_http_status",
            width: 70,
          },
          {
            title: "연속",
            dataIndex: "consecutive_rate_limit_count",
            width: 70,
          },
          {
            title: "Recheck",
            key: "recheck",
            width: 100,
            render: (_: unknown, row: Record<string, unknown>) => {
              const uba = Number(row.user_broker_account_id ?? 0);
              if (!uba) return "-";
              return (
                <Button
                  size="small"
                  loading={recheckRateLimit.isPending}
                  onClick={() => recheckRateLimit.mutate(uba)}
                >
                  Recheck
                </Button>
              );
            },
          },
        ]}
        dataSource={extractRows(rateLimits.data)}
        extra={
          <Button
            size="small"
            onClick={() => void rateLimits.refetch()}
            loading={rateLimits.isFetching}
          >
            새로고침
          </Button>
        }
      />

      <AdminJsonCard
        title="Rate Limit Health"
        loading={rateLimits.isLoading}
        error={rateLimits.error ? toApiError(rateLimits.error) : null}
        data={
          rateLimits.data &&
          typeof rateLimits.data === "object" &&
          "health" in rateLimits.data
            ? (rateLimits.data as { health: unknown }).health
            : rateLimits.data
        }
      />

      <AdminDataTable
        title="보유 스냅샷 (UPBIT)"
        loading={accountSnapshot.isLoading}
        error={
          accountSnapshot.error
            ? toApiError(accountSnapshot.error).status === 404
              ? null
              : toApiError(accountSnapshot.error)
            : null
        }
        rowKey={(r) =>
          cell(r.symbol ?? r.broker_position_snapshot_id ?? JSON.stringify(r))
        }
        columns={[
          { title: "symbol", dataIndex: "symbol", sorter: true },
          { title: "name", dataIndex: "name" },
          { title: "quantity", dataIndex: "quantity" },
          { title: "available", dataIndex: "available_quantity" },
          { title: "avg_buy", dataIndex: "average_purchase_price" },
          { title: "current", dataIndex: "current_price" },
          { title: "eval", dataIndex: "evaluation_amount" },
          { title: "pnl", dataIndex: "profit_loss" },
        ]}
        dataSource={snapshotPositions}
      />
      {accountSnapshot.error &&
      toApiError(accountSnapshot.error).status === 404 ? (
        <Typography.Text type="secondary">
          스냅샷 없음 — 「잔고 동기화」를 실행하세요.
        </Typography.Text>
      ) : null}

      <AdminJsonCard
        title="스냅샷 원본"
        loading={accountSnapshot.isLoading}
        error={
          accountSnapshot.error &&
          toApiError(accountSnapshot.error).status !== 404
            ? toApiError(accountSnapshot.error)
            : null
        }
        data={accountSnapshot.data}
      />

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        Ambiguous 주문 (STEP 8-5-12)
      </Typography.Title>
      <UpbitAmbiguousOrdersPanel />
    </Space>
  );
}
