"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Row,
  Segmented,
  Space,
  Spin,
  Statistic,
  Table,
  Typography,
  message,
} from "antd";
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  PortfolioHistoryItem,
  PortfolioHistoryPeriod,
} from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const PERIOD_OPTIONS: { label: string; value: PortfolioHistoryPeriod }[] = [
  { label: "7일", value: "7d" },
  { label: "30일", value: "30d" },
  { label: "90일", value: "90d" },
  { label: "1년", value: "1y" },
  { label: "전체", value: "all" },
];

function formatNumber(value: unknown): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  return num.toLocaleString("ko-KR");
}

function formatPct(value: unknown): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  return `${num.toFixed(2)}%`;
}

function pnlColor(value: unknown): string | undefined {
  const num = Number(value);
  if (!Number.isFinite(num) || num === 0) return undefined;
  return num < 0 ? "#cf1322" : "#3f8600";
}

interface PortfolioAssetHistorySectionProps {
  accountId: number | null;
}

export function PortfolioAssetHistorySection({
  accountId,
}: PortfolioAssetHistorySectionProps) {
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState<PortfolioHistoryPeriod>("30d");
  const accountReady = accountId !== null && accountId > 0;

  const summaryQuery = useQuery({
    queryKey: queryKeys.user.portfolioAssetSummary({
      account_id: accountId,
      period,
    }),
    queryFn: () =>
      userApi.getPortfolioAssetSummary({
        account_id: accountId!,
        period,
      }),
    enabled: accountReady,
  });

  const historyQuery = useQuery({
    queryKey: queryKeys.user.portfolioHistory({
      account_id: accountId,
      period,
    }),
    queryFn: () =>
      userApi.getPortfolioHistory({
        account_id: accountId!,
        period,
      }),
    enabled: accountReady,
  });

  const snapshotMutation = useMutation({
    mutationFn: () =>
      userApi.createPortfolioSnapshot({ account_id: accountId! }),
    onSuccess: async () => {
      message.success("오늘 자산 스냅샷을 저장했습니다.");
      await queryClient.invalidateQueries({
        queryKey: ["user", "portfolio-history"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["user", "portfolio-asset-summary"],
      });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const chartRows = useMemo(() => {
    const items = historyQuery.data?.items ?? [];
    return items.map((row: PortfolioHistoryItem) => ({
      date: row.snapshot_date,
      total_asset: Number(row.total_asset),
      market_value: Number(row.market_value),
      cash: Number(row.cash),
      daily_profit: Number(row.daily_profit),
      daily_profit_rate: Number(row.daily_profit_rate),
      total_return_rate: Number(row.total_return_rate),
    }));
  }, [historyQuery.data]);

  const summary = summaryQuery.data;
  const isLoading = summaryQuery.isLoading || historyQuery.isLoading;
  const error = summaryQuery.error || historyQuery.error;

  if (!accountReady) {
    return (
      <Card title="자산 변화" size="small">
        <Empty description="계좌를 불러오는 중입니다." />
      </Card>
    );
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card
        title="자산 요약 (이력 기반)"
        size="small"
        extra={
          <Space wrap>
            <Segmented
              size="small"
              value={period}
              options={PERIOD_OPTIONS}
              onChange={(value) =>
                setPeriod(value as PortfolioHistoryPeriod)
              }
            />
            <Button
              size="small"
              onClick={() => snapshotMutation.mutate()}
              loading={snapshotMutation.isPending}
            >
              오늘 스냅샷
            </Button>
          </Space>
        }
      >
        {error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(error).message}
            style={{ marginBottom: 12 }}
          />
        ) : null}
        <Spin spinning={isLoading}>
          <Row gutter={[16, 16]}>
            <Col xs={12} sm={8} lg={4}>
              <Statistic
                title="총자산"
                value={formatNumber(summary?.current_total_asset)}
              />
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <Statistic
                title="오늘 손익"
                value={formatNumber(summary?.today_profit)}
                styles={{
                  content: { color: pnlColor(summary?.today_profit) },
                }}
              />
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <Statistic
                title="누적 손익"
                value={formatNumber(summary?.cumulative_profit)}
                styles={{
                  content: {
                    color: pnlColor(summary?.cumulative_profit),
                  },
                }}
              />
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <Statistic
                title="기간 수익률"
                value={formatPct(summary?.period_return_rate)}
                styles={{
                  content: {
                    color: pnlColor(summary?.period_return_rate),
                  },
                }}
              />
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <Statistic
                title="MDD"
                value={formatPct(summary?.max_drawdown_pct)}
                styles={{ content: { color: "#cf1322" } }}
              />
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <Statistic
                title="최고/최저"
                value={`${formatNumber(summary?.peak_asset)} / ${formatNumber(summary?.trough_asset)}`}
              />
            </Col>
          </Row>
          <Typography.Paragraph
            type="secondary"
            style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}
          >
            주간 {formatPct(summary?.weekly_return_rate)} · 월간{" "}
            {formatPct(summary?.monthly_return_rate)} · 전체{" "}
            {formatPct(summary?.total_return_rate)} · 스냅샷{" "}
            {summary?.snapshot_count ?? 0}건
          </Typography.Paragraph>
        </Spin>
      </Card>

      <Card title="총자산 추이" size="small">
        {isLoading ? (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        ) : chartRows.length === 0 ? (
          <Empty description="자산 이력이 없습니다. ‘오늘 스냅샷’으로 첫 데이터를 생성하세요." />
        ) : (
          <div style={{ width: "100%", height: 280 }}>
            <ResponsiveContainer>
              <LineChart data={chartRows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) =>
                    Number(v).toLocaleString("ko-KR")
                  }
                />
                <Tooltip
                  formatter={(value) =>
                    formatNumber(value as number)
                  }
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="total_asset"
                  name="총자산"
                  stroke="#1677ff"
                  dot={false}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="평가금액" size="small">
            {chartRows.length === 0 ? (
              <Empty description="데이터 없음" />
            ) : (
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <AreaChart data={chartRows}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip
                      formatter={(value) =>
                        formatNumber(value as number)
                      }
                    />
                    <Area
                      type="monotone"
                      dataKey="market_value"
                      name="평가금액"
                      stroke="#52c41a"
                      fill="#b7eb8f"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="일별 손익" size="small">
            {chartRows.length === 0 ? (
              <Empty description="데이터 없음" />
            ) : (
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={chartRows}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip
                      formatter={(value) =>
                        formatNumber(value as number)
                      }
                    />
                    <Bar
                      dataKey="daily_profit"
                      name="일손익"
                      fill="#722ed1"
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card title="일별 자산 테이블" size="small">
        <Table
          size="small"
          loading={historyQuery.isLoading}
          rowKey={(row) => row.date}
          dataSource={[...chartRows].reverse()}
          locale={{ emptyText: "이력 없음" }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            { title: "날짜", dataIndex: "date", width: 120 },
            {
              title: "총자산",
              dataIndex: "total_asset",
              render: (v: number) => formatNumber(v),
            },
            {
              title: "평가",
              dataIndex: "market_value",
              render: (v: number) => formatNumber(v),
            },
            {
              title: "현금",
              dataIndex: "cash",
              render: (v: number) => formatNumber(v),
            },
            {
              title: "일손익",
              dataIndex: "daily_profit",
              render: (v: number) => (
                <span style={{ color: pnlColor(v) }}>
                  {formatNumber(v)}
                </span>
              ),
            },
            {
              title: "일수익률",
              dataIndex: "daily_profit_rate",
              render: (v: number) => formatPct(v),
            },
            {
              title: "누적수익률",
              dataIndex: "total_return_rate",
              render: (v: number) => formatPct(v),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
