"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  DatePicker,
  Space,
  Table,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";

import type {
  AccountStrategyPerformanceItem,
  AccountStrategyTradeItem,
} from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const { RangePicker } = DatePicker;

interface AccountStrategyPerformancePanelProps {
  accountId: number | null;
  accountType?: string;
}

/** strategy_key — 미식별은 UNATTRIBUTED */
function resolveStrategyKey(row: AccountStrategyPerformanceItem): string {
  if (row.strategy_id == null) {
    return "UNATTRIBUTED";
  }
  return String(row.strategy_id);
}

function formatPnl(value?: string | number | null): string {
  if (value == null || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return num.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

export function AccountStrategyPerformancePanel({
  accountId,
  accountType = "PAPER",
}: AccountStrategyPerformancePanelProps) {
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [selectedStrategyKey, setSelectedStrategyKey] = useState<string | null>(
    null,
  );

  const dateParams = useMemo(
    () => ({
      account_type: accountType,
      date_from: dateRange?.[0]?.startOf("day").toISOString(),
      date_to: dateRange?.[1]?.endOf("day").toISOString(),
    }),
    [accountType, dateRange],
  );

  const accountReady = accountId != null && accountId > 0;

  const performanceQuery = useQuery({
    queryKey: queryKeys.user.accountStrategyPerformance(
      accountId ?? 0,
      dateParams,
    ),
    queryFn: () =>
      userApi.getAccountStrategyPerformance(accountId!, dateParams),
    enabled: accountReady,
  });

  const tradesQuery = useQuery({
    queryKey: queryKeys.user.accountStrategyTrades(
      accountId ?? 0,
      selectedStrategyKey ?? "",
      dateParams,
    ),
    queryFn: () =>
      userApi.getAccountStrategyTrades(
        accountId!,
        selectedStrategyKey!,
        dateParams,
      ),
    enabled: accountReady && selectedStrategyKey != null,
  });

  const performanceRows = performanceQuery.data?.items ?? [];

  const selectedLabel = useMemo(() => {
    if (!selectedStrategyKey) return null;
    const row = performanceRows.find(
      (item) => resolveStrategyKey(item) === selectedStrategyKey,
    );
    return row?.strategy_name ?? selectedStrategyKey;
  }, [performanceRows, selectedStrategyKey]);

  if (!accountReady) {
    return null;
  }

  return (
    <Card size="small" title="전략별 실거래 성과 (Paper/LIVE 원장)">
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="백테스트 결과가 아닙니다"
          description="Paper/LIVE 계좌 원장(체결·손익) 기준 집계입니다. 백테스트 성과와 혼동하지 마세요. 전략이 연결되지 않은 체결은 「전략 미식별」로 표시됩니다."
        />

        <RangePicker
          value={dateRange}
          onChange={(values) => {
            setDateRange(
              values && values[0] && values[1]
                ? [values[0], values[1]]
                : null,
            );
            setSelectedStrategyKey(null);
          }}
        />

        {performanceQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(performanceQuery.error).message}
          />
        ) : null}

        <Table<AccountStrategyPerformanceItem>
          size="small"
          loading={performanceQuery.isLoading}
          rowKey={(row) => resolveStrategyKey(row)}
          dataSource={performanceRows}
          locale={{ emptyText: "전략별 성과 데이터가 없습니다." }}
          pagination={false}
          onRow={(row) => ({
            onClick: () => setSelectedStrategyKey(resolveStrategyKey(row)),
            style: {
              cursor: "pointer",
              background:
                selectedStrategyKey === resolveStrategyKey(row)
                  ? "rgba(22, 119, 255, 0.08)"
                  : undefined,
            },
          })}
          columns={[
            {
              title: "전략",
              dataIndex: "strategy_name",
              render: (value?: string | null) => value ?? "전략 미식별",
            },
            {
              title: "코드",
              dataIndex: "strategy_code",
              width: 120,
              render: (value?: string | null) => value ?? "-",
            },
            {
              title: "주문",
              dataIndex: "order_count",
              width: 70,
            },
            {
              title: "체결",
              dataIndex: "fill_count",
              width: 70,
            },
            {
              title: "실현손익",
              dataIndex: "realized_pnl",
              width: 110,
              render: formatPnl,
            },
            {
              title: "순손익",
              dataIndex: "net_pnl",
              width: 110,
              render: formatPnl,
            },
            {
              title: "승률",
              dataIndex: "win_rate",
              width: 80,
              render: (value?: number | null) =>
                value == null ? "-" : `${(value * 100).toFixed(1)}%`,
            },
            {
              title: "최근거래",
              dataIndex: "last_trade_at",
              width: 140,
              render: (value?: string | null) =>
                value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-",
            },
          ]}
        />

        {selectedStrategyKey ? (
          <>
            <Typography.Text type="secondary">
              선택: {selectedLabel} — 행을 다시 클릭하면 해제됩니다.
            </Typography.Text>
            {tradesQuery.error ? (
              <Alert
                type="error"
                showIcon
                title={toApiError(tradesQuery.error).message}
              />
            ) : null}
            <Table<AccountStrategyTradeItem>
              size="small"
              loading={tradesQuery.isLoading}
              rowKey={(row, index) =>
                String(
                  row.order_id ??
                    row.execution_id ??
                    row.trade_id ??
                    `${index}`,
                )
              }
              dataSource={tradesQuery.data?.items ?? []}
              locale={{ emptyText: "해당 전략의 거래 내역이 없습니다." }}
              pagination={{ pageSize: 10, showSizeChanger: false }}
              columns={[
                {
                  title: "시각",
                  dataIndex: "traded_at",
                  width: 140,
                  render: (value?: string | null) =>
                    value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-",
                },
                { title: "종목", dataIndex: "symbol", width: 100 },
                { title: "구분", dataIndex: "side", width: 80 },
                {
                  title: "수량",
                  dataIndex: "quantity",
                  width: 90,
                  render: formatPnl,
                },
                {
                  title: "체결가",
                  dataIndex: "fill_price",
                  width: 100,
                  render: formatPnl,
                },
                {
                  title: "손익",
                  dataIndex: "realized_profit_loss",
                  width: 100,
                  render: formatPnl,
                },
              ]}
            />
          </>
        ) : (
          <Typography.Text type="secondary">
            전략 행을 클릭하면 거래 내역을 불러옵니다.
          </Typography.Text>
        )}
      </Space>
    </Card>
  );
}
