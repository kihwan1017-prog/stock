"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Grid,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { queryKeys } from "@/lib/query/queryKeys";

import {
  BROKER_FILTER_OPTIONS,
  formatKrw,
  formatPct,
  parsePerformanceSummary,
  PERIOD_FILTER_OPTIONS,
  pnlColor,
  type BrokerFilter,
  type PeriodFilter,
} from "./autoTradingPerformanceHelpers";
import {
  CHART_SEGMENTS,
  type PerformanceChartType,
} from "./dashboardTabState";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

type Props = {
  enabled: boolean;
  broker: BrokerFilter;
  period: PeriodFilter;
  chart: PerformanceChartType;
  onBrokerChange: (v: BrokerFilter) => void;
  onPeriodChange: (v: PeriodFilter) => void;
  onChartChange: (v: PerformanceChartType) => void;
  refreshMs?: number;
};

const CHART_HEIGHT = 280;

export function DashboardPerformanceTab({
  enabled,
  broker,
  period,
  chart,
  onBrokerChange,
  onPeriodChange,
  onChartChange,
  refreshMs = 60_000,
}: Props) {
  const screens = Grid.useBreakpoint();
  const [detailOpen, setDetailOpen] = useState(false);

  const perfQ = useQuery({
    queryKey: queryKeys.admin.autotradingPerformance({ broker, period }),
    queryFn: () =>
      adminApi.getAdminAutotradingPerformance({ broker, period }),
    enabled,
    refetchInterval: enabled && refreshMs > 0 ? refreshMs : false,
    staleTime: 45_000,
    placeholderData: (prev) => prev,
  });

  const data = rec(perfQ.data);
  const summary = parsePerformanceSummary(data.summary);
  const hasClosed = summary.closedTradeCount > 0;

  const dailyChart = useMemo(
    () =>
      extractRows(data.daily_returns).map((r) => {
        const row = rec(r);
        return {
          label: String(row.trading_date ?? "").slice(5),
          value: Number(row.daily_return_pct ?? 0),
          pnl: Number(row.realized_pnl ?? 0),
        };
      }),
    [data.daily_returns],
  );

  const cumulativeChart = useMemo(
    () =>
      extractRows(data.cumulative_returns).map((r) => {
        const row = rec(r);
        return {
          label: String(row.trading_date ?? "").slice(5),
          value: Number(row.cumulative_return_pct ?? 0),
        };
      }),
    [data.cumulative_returns],
  );

  const symbolChart = useMemo(
    () =>
      extractRows(data.symbol_performance).map((r) => {
        const row = rec(r);
        return {
          label: String(row.symbol ?? "").replace("KRW-", ""),
          value: Number(row.return_pct ?? 0),
          pnl: Number(row.realized_pnl ?? 0),
        };
      }),
    [data.symbol_performance],
  );

  const exitChart = useMemo(
    () =>
      extractRows(data.exit_reason_performance).map((r) => {
        const row = rec(r);
        return {
          label: String(row.exit_reason_label_ko ?? row.exit_reason_category),
          value: Number(row.avg_return_pct ?? 0),
          pnl: Number(row.total_realized_pnl ?? 0),
        };
      }),
    [data.exit_reason_performance],
  );

  const distChart = useMemo(
    () =>
      extractRows(data.return_distribution).map((r) => {
        const row = rec(r);
        return { label: String(row.bucket), value: Number(row.count ?? 0) };
      }),
    [data.return_distribution],
  );

  const chartTitle: Record<PerformanceChartType, string> = {
    daily: "일별 자동매매 수익률",
    cumulative: "누적 자동매매 수익률",
    symbol: "종목별 자동매매 성과",
    exit_reason: "청산 유형별 성과",
    distribution: "수익률 구간 분포",
  };

  const renderMainChart = () => {
    if (!hasClosed) {
      return (
        <Typography.Text type="secondary">거래 데이터 없음</Typography.Text>
      );
    }

    if (chart === "daily") {
      return (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <BarChart data={dailyChart}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis unit="%" />
            <Tooltip />
            <Bar dataKey="value" name="수익률(%)">
              {dailyChart.map((entry, i) => (
                <Cell
                  key={i}
                  fill={entry.value >= 0 ? "#3f8600" : "#cf1322"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    }

    if (chart === "cumulative") {
      return (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <LineChart data={cumulativeChart}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis unit="%" />
            <Tooltip />
            <Line
              type="monotone"
              dataKey="value"
              name="누적 수익률(%)"
              stroke="#1677ff"
              dot
            />
          </LineChart>
        </ResponsiveContainer>
      );
    }

    const barData =
      chart === "symbol"
        ? symbolChart
        : chart === "exit_reason"
          ? exitChart
          : distChart;

    return (
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={barData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" />
          <YAxis />
          <Tooltip />
          <Bar
            dataKey="value"
            name={chart === "distribution" ? "거래수" : "수익률(%)"}
            fill="#1677ff"
          />
        </BarChart>
      </ResponsiveContainer>
    );
  };

  const chartSelector = screens.md ? (
    <Segmented
      options={CHART_SEGMENTS.map((c) => ({
        label: c.label,
        value: c.value,
      }))}
      value={chart}
      onChange={(v) => onChartChange(v as PerformanceChartType)}
    />
  ) : (
    <Select
      style={{ minWidth: 140 }}
      value={chart}
      onChange={(v) => onChartChange(v as PerformanceChartType)}
      options={CHART_SEGMENTS.map((c) => ({
        label: c.label,
        value: c.value,
      }))}
    />
  );

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="AUTO 전용 성과"
        description="일반매매(MANUAL) 및 계좌 전체 손익은 포함하지 않습니다."
      />

      <Card size="small">
        <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
          <Space wrap>
            <Select
              value={broker}
              onChange={onBrokerChange}
              options={BROKER_FILTER_OPTIONS}
              style={{ width: 110 }}
            />
            <Select
              value={period}
              onChange={onPeriodChange}
              options={PERIOD_FILTER_OPTIONS}
              style={{ width: 100 }}
            />
            {chartSelector}
          </Space>
          <Button onClick={() => perfQ.refetch()} loading={perfQ.isFetching}>
            조회
          </Button>
        </Space>
      </Card>

      <Card size="small" loading={perfQ.isLoading && !perfQ.data}>
        <Row gutter={[12, 12]}>
          <Col xs={12} sm={6}>
            <Statistic
              title="실현손익"
              value={summary.periodRealizedPnl ?? 0}
              precision={0}
              suffix="원"
              styles={{
                content: { color: pnlColor(summary.periodRealizedPnl) },
              }}
            />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic
              title="수익률"
              value={formatPct(summary.periodReturnPct)}
            />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic
              title="승률"
              value={
                summary.winRatePct != null
                  ? `${summary.winRatePct.toFixed(1)}%`
                  : "—"
              }
            />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic title="거래수" value={summary.closedTradeCount} />
          </Col>
        </Row>
      </Card>

      <Card size="small" title={chartTitle[chart]}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          {String(data.return_formula_note ?? "")}
        </Typography.Paragraph>
        {renderMainChart()}
      </Card>

      <Card size="small">
        <Button type="link" onClick={() => setDetailOpen((o) => !o)}>
          {detailOpen ? "상세 거래 접기 ▲" : "상세 거래 보기 ▼"}
        </Button>
        {detailOpen ? (
          <Table
            size="small"
            pagination={{ pageSize: 10 }}
            scroll={{ x: 800 }}
            rowKey={(r) => String(rec(r).binding_id)}
            dataSource={extractRows(data.recent_closed_trades).map((r) =>
              rec(r),
            )}
            columns={[
              { title: "거래소", dataIndex: "broker_code" },
              { title: "종목", dataIndex: "symbol" },
              { title: "순손익", dataIndex: "net_pnl", render: (v) => formatKrw(Number(v), 2) },
              { title: "수익률", dataIndex: "return_pct", render: (v) => formatPct(Number(v)) },
              { title: "청산", dataIndex: "exit_reason_label_ko" },
              { title: "시간", dataIndex: "closed_at", render: (v) => new Date(String(v)).toLocaleString("ko-KR") },
            ]}
          />
        ) : null}
      </Card>
    </Space>
  );
}
