"use client";

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
import { useState } from "react";

import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";

import {
  formatKrw,
  formatPct,
  parsePerformanceSummary,
  pnlColor,
  durationLabel,
  type BrokerFilter,
  type PeriodFilter,
} from "./autoTradingPerformanceHelpers";
import { DashboardPerformanceChart } from "./dashboardCharts";
import {
  CHART_OPTIONS,
  PERIOD_OPTIONS,
  type PerformanceChartType,
} from "./dashboardTabState";
import { useAutotradingPerformanceQuery } from "./useAutotradingPerformanceQuery";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

const CHART_TITLES: Record<PerformanceChartType, string> = {
  cumulative_pnl: "누적 실현손익",
  daily_pnl: "일별 실현손익",
  cumulative_return: "누적 수익률",
  symbol_pnl: "종목별 실현손익",
  symbol_return: "종목별 수익률",
  win_loss: "승 / 패 비율",
  exit_reason: "Exit Reason 분포",
  trade_pnl: "거래별 손익",
  holding_return: "보유시간 vs 수익률",
  broker_compare: "거래소 비교",
};

type Props = {
  enabled: boolean;
  broker: BrokerFilter;
  period: PeriodFilter;
  chart: PerformanceChartType;
  onPeriodChange: (v: PeriodFilter) => void;
  onChartChange: (v: PerformanceChartType) => void;
  refreshMs?: number;
};

export function DashboardPerformanceTab({
  enabled,
  broker,
  period,
  chart,
  onPeriodChange,
  onChartChange,
  refreshMs = 60_000,
}: Props) {
  const screens = Grid.useBreakpoint();
  const [detailOpen, setDetailOpen] = useState(false);

  const perfQ = useAutotradingPerformanceQuery({
    broker,
    period,
    enabled,
    refreshMs,
  });

  const data = rec(perfQ.data);
  const summary = parsePerformanceSummary(data.summary);
  const lowSample = data.low_sample_warning === true;
  const lowSampleMessage = String(data.low_sample_message ?? "");

  const chartSelector = screens.md ? (
    <Segmented
      options={CHART_OPTIONS.map((c) => ({
        label: c.label,
        value: c.value,
      }))}
      value={chart}
      onChange={(v) => onChartChange(v as PerformanceChartType)}
    />
  ) : (
    <Select
      style={{ minWidth: 160 }}
      value={chart}
      onChange={(v) => onChartChange(v as PerformanceChartType)}
      options={CHART_OPTIONS}
    />
  );

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="AUTO 전용 성과 분석"
        description="일반매매(MANUAL) 및 계좌 전체 손익은 포함하지 않습니다."
      />

      <Card size="small">
        <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
          <Space wrap>
            <Select
              value={period}
              onChange={onPeriodChange}
              options={PERIOD_OPTIONS}
              style={{ width: 100 }}
            />
            {chartSelector}
          </Space>
          <Button onClick={() => perfQ.refetch()} loading={perfQ.isFetching}>
            조회
          </Button>
        </Space>
      </Card>

      {lowSample ? (
        <Alert
          type="warning"
          showIcon
          title="표본 부족"
          description={
            lowSampleMessage ||
            "완료된 자동매매 거래가 적습니다. 거래 데이터가 더 쌓인 후 성과를 판단하세요."
          }
        />
      ) : null}

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
            <Statistic title="수익률" value={formatPct(summary.periodReturnPct)} />
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

      <Card
        size="small"
        title={CHART_TITLES[chart]}
        loading={perfQ.isLoading && !perfQ.data}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          {String(data.return_formula_note ?? "")}
        </Typography.Paragraph>
        {perfQ.isError ? (
          <Alert type="error" title="차트 데이터 로드 실패" />
        ) : (
          <DashboardPerformanceChart
            chart={chart}
            data={data}
            broker={broker}
          />
        )}
      </Card>

      <Card size="small">
        <Button type="link" onClick={() => setDetailOpen((o) => !o)}>
          {detailOpen ? "상세 AUTO 거래 접기 ▲" : "상세 AUTO 거래 보기 ▼"}
        </Button>
        {detailOpen ? (
          <Table
            size="small"
            pagination={{ pageSize: 10 }}
            scroll={{ x: 1100 }}
            rowKey={(r) => String(rec(r).binding_id)}
            dataSource={extractRows(data.round_trips ?? data.recent_closed_trades).map(
              (r) => rec(r),
            )}
            columns={[
              { title: "거래소/증권사", dataIndex: "broker_code", width: 72 },
              { title: "종목", dataIndex: "symbol" },
              { title: "Entry", dataIndex: "entry_price", width: 72 },
              { title: "Exit", dataIndex: "exit_price", width: 72 },
              { title: "Qty", dataIndex: "quantity", width: 64 },
              {
                title: "Gross",
                dataIndex: "gross_pnl",
                render: (v) => formatKrw(Number(v), 2),
              },
              {
                title: "Fee",
                dataIndex: "fees",
                render: (v) => formatKrw(Number(v), 2),
              },
              {
                title: "Net",
                dataIndex: "net_pnl",
                render: (v) => formatKrw(Number(v), 2),
              },
              {
                title: "Return",
                dataIndex: "return_pct",
                render: (v) => formatPct(Number(v)),
              },
              {
                title: "Holding",
                dataIndex: "duration_sec",
                render: (v) => durationLabel(Number(v)),
              },
              { title: "Exit", dataIndex: "exit_reason_label_ko" },
              { title: "Opened", dataIndex: "opened_at", ellipsis: true },
              { title: "Closed", dataIndex: "closed_at", ellipsis: true },
            ]}
          />
        ) : null}
      </Card>
    </Space>
  );
}
