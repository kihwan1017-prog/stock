"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, InputNumber, Space, Typography } from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { UpbitAmbiguousOrdersPanel } from "@/features/admin/upbit/UpbitAmbiguousOrdersPanel";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminUpbitPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [ubaId, setUbaId] = useState<number | null>(null);

  const markets = useQuery({
    queryKey: queryKeys.admin.upbitMarkets(),
    queryFn: adminApi.getUpbitMarkets,
  });

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

  const syncInstruments = useMutation({
    mutationFn: adminApi.syncUpbitInstruments,
    onSuccess: () => {
      message.success("업비트 종목 동기화 요청 완료");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.upbitMarkets() });
    },
    onError: (e) => message.error(toApiError(e).message),
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
    mutationFn: (ubaId: number) => adminApi.recheckUpbitRateLimits(ubaId),
    onSuccess: () => {
      message.success("Rate Limit 상태 재조회 완료 (강제 해제 없음)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitRateLimits(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rows = extractRows(markets.data).length
    ? extractRows(markets.data)
    : Array.isArray(markets.data)
      ? (markets.data as Record<string, unknown>[])
      : [];

  const snapshotPositions =
    accountSnapshot.data &&
    typeof accountSnapshot.data === "object" &&
    "positions" in accountSnapshot.data &&
    Array.isArray((accountSnapshot.data as { positions?: unknown }).positions)
      ? ((accountSnapshot.data as { positions: Record<string, unknown>[] })
          .positions)
      : [];

  return (
    <AdminPageShell
      title="업비트 관리"
      description="시세·종목 동기화 · 인증/잔고 스냅샷 (STEP2)"
      extra={
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
          <Button
            type="primary"
            loading={syncInstruments.isPending}
            onClick={() => syncInstruments.mutate()}
          >
            종목 동기화
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Private 키는 env(`UPBIT_ACCESS_KEY` / `UPBIT_SECRET_KEY`)만 사용합니다.
          `UPBIT_USE_MOCK=true`이면 실호출 없이 mock 잔고로 검증합니다. 실주문은
          비활성(`UPBIT_LIVE_ORDER_ENABLED=false`)이 기본입니다.
        </Typography.Paragraph>

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

        <AdminDataTable
          title="GET /upbit/markets"
          loading={markets.isLoading}
          error={markets.error ? toApiError(markets.error) : null}
          rowKey={(r) => cell(r.market ?? r.symbol ?? JSON.stringify(r))}
          columns={[
            { title: "market", dataIndex: "market", sorter: true },
            { title: "korean_name", dataIndex: "korean_name" },
            { title: "english_name", dataIndex: "english_name" },
          ]}
          dataSource={rows}
        />
        <AdminJsonCard
          title="마켓 원본 응답"
          loading={markets.isLoading}
          error={markets.error ? toApiError(markets.error) : null}
          data={markets.data}
        />
      </Space>
    </AdminPageShell>
  );
}
