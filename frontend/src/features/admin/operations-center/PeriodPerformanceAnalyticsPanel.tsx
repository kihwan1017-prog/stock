"use client";

/**
 * 기간별 AUTO 성과 분석 패널 — 날짜 필터 + KPI + 차트 + 종목표 + 최근거래 + Drawer.
 * REAL 정책 변경 없음 (조회 전용).
 */

import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Grid,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";

import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

import {
  DATE_PRESET_OPTIONS,
  durationLabel,
  formatKrw,
  formatPct,
  isSingleDayPeriod,
  MAX_PERFORMANCE_RANGE_DAYS,
  parsePerformanceSummary,
  pnlColor,
  type BrokerFilter,
  type DatePreset,
  type PeriodFilter,
} from "./autoTradingPerformanceHelpers";
import { DashboardPerformanceChart } from "./dashboardCharts";
import {
  CHART_OPTIONS,
  type PerformanceChartType,
} from "./dashboardTabState";
import { SymbolPerformanceDrawer } from "./SymbolPerformanceDrawer";
import { useAutotradingPerformanceQuery } from "./useAutotradingPerformanceQuery";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

type SymbolRow = Record<string, unknown>;

type Props = {
  broker?: BrokerFilter;
  enabled?: boolean;
  refreshMs?: number;
  userBrokerAccountId?: number | null;
  showChartSelector?: boolean;
  defaultPreset?: DatePreset;
};

function resolveDates(
  preset: DatePreset,
  custom: [Dayjs | null, Dayjs | null] | null,
): { start: string; end: string; period: PeriodFilter } {
  const today = dayjs().startOf("day");
  if (preset === "TODAY") {
    const d = today.format("YYYY-MM-DD");
    return { start: d, end: d, period: "TODAY" };
  }
  if (preset === "YESTERDAY") {
    const d = today.subtract(1, "day").format("YYYY-MM-DD");
    return { start: d, end: d, period: "TODAY" };
  }
  if (preset === "7D") {
    return {
      start: today.subtract(6, "day").format("YYYY-MM-DD"),
      end: today.format("YYYY-MM-DD"),
      period: "7D",
    };
  }
  if (preset === "30D") {
    return {
      start: today.subtract(29, "day").format("YYYY-MM-DD"),
      end: today.format("YYYY-MM-DD"),
      period: "30D",
    };
  }
  const start = custom?.[0] ?? today;
  let end = custom?.[1] ?? today;
  if (end.diff(start, "day") > MAX_PERFORMANCE_RANGE_DAYS) {
    end = start.add(MAX_PERFORMANCE_RANGE_DAYS, "day");
  }
  return {
    start: start.format("YYYY-MM-DD"),
    end: end.format("YYYY-MM-DD"),
    period: "TODAY",
  };
}

export function PeriodPerformanceAnalyticsPanel({
  broker = "UPBIT",
  enabled = true,
  refreshMs = 60_000,
  userBrokerAccountId = null,
  showChartSelector = true,
  defaultPreset = "TODAY",
}: Props) {
  const screens = Grid.useBreakpoint();
  const [preset, setPreset] = useState<DatePreset>(defaultPreset);
  const [customRange, setCustomRange] = useState<
    [Dayjs | null, Dayjs | null] | null
  >(null);
  const [applied, setApplied] = useState(() =>
    resolveDates(defaultPreset, null),
  );
  const [chart, setChart] = useState<PerformanceChartType>(() => {
    const init = resolveDates(defaultPreset, null);
    return isSingleDayPeriod(init.start, init.end)
      ? "trade_pnl"
      : "cumulative_pnl";
  });
  const [drawerSymbol, setDrawerSymbol] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const applyFilter = (nextPreset: DatePreset, range = customRange) => {
    const next = resolveDates(nextPreset, range);
    setApplied(next);
    setChart(
      isSingleDayPeriod(next.start, next.end) ? "trade_pnl" : "cumulative_pnl",
    );
    // 기간 변경 시 stale Drawer 방지
    setDrawerOpen(false);
    setDrawerSymbol(null);
  };
  const perfQ = useAutotradingPerformanceQuery({
    broker,
    period: applied.period,
    enabled,
    refreshMs,
    startDate: applied.start,
    endDate: applied.end,
    userBrokerAccountId,
  });

  const data = rec(perfQ.data);
  const summary = parsePerformanceSummary(data.summary);
  const summaryRaw = rec(data.summary);
  const window = rec(data.period_window);
  const periodLabel = String(
    window.label ?? `${applied.start} ~ ${applied.end}`,
  );
  const isTodayOnly =
    applied.start === applied.end &&
    applied.start === dayjs().format("YYYY-MM-DD");
  const netTitle = isTodayOnly ? "오늘 순손익" : "기간 순손익";
  const netPnl = summary.periodNetPnl;
  const fees = summary.periodFees;
  const gross = summary.periodGrossPnl;
  const pf = summary.periodProfitFactor;
  // 매수 건수 내림차순 (동점이면 순손익 오름차순으로 안정 정렬)
  const symbolRows = extractRows(data.symbol_performance)
    .map((r) => rec(r))
    .sort((a, b) => {
      const buyDiff = Number(b.buy_count ?? 0) - Number(a.buy_count ?? 0);
      if (buyDiff !== 0) return buyDiff;
      return Number(a.net_pnl ?? 0) - Number(b.net_pnl ?? 0);
    });
  const totals = rec(data.symbol_performance_totals);
  const recent = extractRows(data.recent_closed_trades).map((r) => rec(r));
  const lowSample = data.low_sample_warning === true;

  const symbolColumns: ColumnsType<SymbolRow> = useMemo(
    () => [
      {
        title: "종목",
        dataIndex: "symbol",
        fixed: "left",
        width: 110,
        render: (v, row) => (
          <Button
            type="link"
            style={{ padding: 0 }}
            onClick={() => {
              setDrawerSymbol(String(v));
              setDrawerOpen(true);
            }}
          >
            {String(v)}
            {row.has_open_auto === true ? (
              <Tag color="blue" style={{ marginLeft: 6 }}>
                보유
              </Tag>
            ) : null}
          </Button>
        ),
      },
      {
        title: "종목명",
        dataIndex: "symbol_name",
        width: 90,
        render: (v) => (v ? String(v) : "—"),
      },
      {
        title: "매수",
        dataIndex: "buy_count",
        // 기본: 매수 건수 많은 종목부터
        defaultSortOrder: "descend",
        sorter: (a, b) => Number(a.buy_count) - Number(b.buy_count),
        width: 64,
      },
      { title: "매도", dataIndex: "sell_count", width: 64 },
      { title: "RT", dataIndex: "round_trip_count", width: 56 },
      {
        title: "매수금액",
        dataIndex: "buy_amount",
        render: (v) => formatKrw(num(v), 0),
      },
      {
        title: "매도금액",
        dataIndex: "sell_amount",
        render: (v) => formatKrw(num(v), 0),
      },
      {
        title: "수수료 전",
        dataIndex: "gross_pnl",
        sorter: (a, b) => Number(a.gross_pnl) - Number(b.gross_pnl),
        render: (v) => (
          <span style={{ color: pnlColor(num(v)) }}>{formatKrw(num(v), 0)}</span>
        ),
      },
      {
        title: "수수료",
        dataIndex: "fees",
        sorter: (a, b) => Number(a.fees) - Number(b.fees),
        render: (v) => formatKrw(num(v), 0),
      },
      {
        title: "순손익",
        dataIndex: "net_pnl",
        sorter: (a, b) => Number(a.net_pnl) - Number(b.net_pnl),
        render: (v) => (
          <span style={{ color: pnlColor(num(v)) }}>{formatKrw(num(v), 0)}</span>
        ),
      },
      { title: "수익", dataIndex: "win_count", width: 56 },
      { title: "손실", dataIndex: "loss_count", width: 56 },
      {
        title: "승률",
        dataIndex: "win_rate_pct",
        render: (v) => formatPct(num(v)),
      },
      {
        title: "평균보유",
        dataIndex: "avg_hold_sec",
        render: (v) => durationLabel(num(v) ?? undefined),
      },
      {
        title: "수익률",
        dataIndex: "return_pct",
        render: (v) => formatPct(num(v)),
      },
      {
        title: "주요 Exit",
        dataIndex: "primary_exit_reason_label_ko",
        ellipsis: true,
      },
      {
        title: "최근 청산",
        dataIndex: "last_closed_at",
        ellipsis: true,
        width: 140,
      },
    ],
    [],
  );

  const chartSelector = showChartSelector ? (
    screens.md ? (
      <Segmented
        options={CHART_OPTIONS.map((c) => ({
          label: c.label,
          value: c.value,
        }))}
        value={chart}
        onChange={(v) => setChart(v as PerformanceChartType)}
      />
    ) : (
      <Select
        style={{ minWidth: 160 }}
        value={chart}
        onChange={(v) => setChart(v as PerformanceChartType)}
        options={CHART_OPTIONS}
      />
    )
  ) : null;

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="AUTO 전용 성과 분석"
        description="STRATEGY_OWNED(AUTO)만 집계합니다. MANUAL/UNKNOWN/미체결/취소는 제외. 순손익 = 수수료 전 손익 − 수수료."
      />

      <Card size="small" title="조회 기간">
        <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
          <Space wrap>
            <Segmented
              options={DATE_PRESET_OPTIONS.map((o) => ({
                label: o.label,
                value: o.value,
              }))}
              value={preset}
              onChange={(v) => {
                const next = v as DatePreset;
                setPreset(next);
                if (next !== "CUSTOM") {
                  applyFilter(next, null);
                }
              }}
            />
            {preset === "CUSTOM" ? (
              <DatePicker.RangePicker
                value={customRange}
                disabledDate={(current) => {
                  if (!current) return false;
                  const today = dayjs().endOf("day");
                  return current.isAfter(today);
                }}
                onChange={(vals) => {
                  const range = (vals as [Dayjs | null, Dayjs | null] | null) ?? null;
                  setCustomRange(range);
                }}
              />
            ) : null}
            <Typography.Text type="secondary">
              조회기간: {periodLabel}
            </Typography.Text>
          </Space>
          <Space>
            <Button
              type="primary"
              onClick={() => applyFilter(preset, customRange)}
              loading={perfQ.isFetching}
            >
              조회
            </Button>
            <Button onClick={() => perfQ.refetch()} loading={perfQ.isFetching}>
              새로고침
            </Button>
          </Space>
        </Space>
      </Card>

      {perfQ.isError ? (
        <Alert
          type="error"
          showIcon
          title="성과 데이터를 불러오지 못했습니다."
          description={toApiError(perfQ.error).message}
        />
      ) : null}

      {lowSample ? (
        <Alert
          type="warning"
          showIcon
          title="표본 부족"
          description={String(data.low_sample_message ?? "")}
        />
      ) : null}

      <Card size="small" loading={perfQ.isLoading && !perfQ.data}>
        <Row gutter={[12, 12]}>
          <Col xs={12} sm={8} md={4}>
            <Tooltip title="수수료를 포함한 실현 손익입니다.">
              <Statistic
                title={netTitle}
                value={netPnl ?? 0}
                precision={0}
                suffix="원"
                styles={{ content: { color: pnlColor(netPnl) } }}
              />
            </Tooltip>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Tooltip title="선택 기간의 매수·매도 거래 수수료 합계입니다.">
              <Statistic
                title="수수료"
                value={fees ?? 0}
                precision={0}
                suffix="원"
              />
            </Tooltip>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Tooltip title="수수료 차감 전 실현 손익입니다.">
              <Statistic
                title="수수료 전 손익"
                value={gross ?? 0}
                precision={0}
                suffix="원"
                styles={{ content: { color: pnlColor(gross) } }}
              />
            </Tooltip>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="AUTO 완료거래" value={summary.closedTradeCount} />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="승률"
              value={
                summary.winRatePct != null
                  ? `${summary.winRatePct.toFixed(2)}%`
                  : "—"
              }
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="Profit Factor" value={pf ?? "—"} />
          </Col>
        </Row>
        {num(summaryRaw.period_gross_minus_fees_delta) != null &&
        Math.abs(Number(summaryRaw.period_gross_minus_fees_delta)) > 0.01 ? (
          <Alert
            style={{ marginTop: 12 }}
            type="warning"
            showIcon
            title="Gross−Fee≈Net 정합 경고"
            description={`delta=${String(summaryRaw.period_gross_minus_fees_delta)}`}
          />
        ) : null}
      </Card>

      <Card
        size="small"
        title="성과 차트"
        extra={chartSelector}
        loading={perfQ.isLoading && !perfQ.data}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          {String(data.return_formula_note ?? "")}
        </Typography.Paragraph>
        {perfQ.isError ? (
          <Alert type="error" title="차트 데이터 로드 실패" />
        ) : summary.closedTradeCount === 0 ? (
          <Empty description="선택 기간에 AUTO 거래가 없습니다." />
        ) : (
          <DashboardPerformanceChart chart={chart} data={data} broker={broker} />
        )}
      </Card>

      <Card size="small" title="종목별 AUTO 거래 성과">
        {symbolRows.length === 0 ? (
          <Empty description="선택 기간에 AUTO 거래가 없습니다." />
        ) : (
          <Table<SymbolRow>
            size="small"
            rowKey={(r) => String(r.symbol)}
            dataSource={symbolRows}
            columns={symbolColumns}
            scroll={{ x: 1600 }}
            pagination={{ pageSize: 15 }}
            summary={() => (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0}>TOTAL</Table.Summary.Cell>
                <Table.Summary.Cell index={1} />
                <Table.Summary.Cell index={2}>
                  {Number(totals.buy_count ?? 0)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={3}>
                  {Number(totals.sell_count ?? 0)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={4}>
                  {Number(totals.round_trip_count ?? 0)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={5} />
                <Table.Summary.Cell index={6} />
                <Table.Summary.Cell index={7}>
                  {formatKrw(num(totals.gross_pnl), 0)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={8}>
                  {formatKrw(num(totals.fees), 0)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={9}>
                  <span style={{ color: pnlColor(num(totals.net_pnl)) }}>
                    {formatKrw(num(totals.net_pnl), 0)}
                  </span>
                </Table.Summary.Cell>
              </Table.Summary.Row>
            )}
          />
        )}
      </Card>

      <Card size="small" title="최근 AUTO 거래">
        {recent.length === 0 ? (
          <Empty description="선택 기간에 AUTO 거래가 없습니다." />
        ) : (
          <Table
            size="small"
            pagination={{ pageSize: 10 }}
            scroll={{ x: 1100 }}
            rowKey={(r) => String(rec(r).binding_id)}
            dataSource={recent}
            columns={[
              { title: "종목", dataIndex: "symbol" },
              { title: "Entry", dataIndex: "entry_price", width: 72 },
              { title: "Exit", dataIndex: "exit_price", width: 72 },
              {
                title: "Gross",
                dataIndex: "gross_pnl",
                render: (v) => formatKrw(num(v), 2),
              },
              {
                title: "Fee",
                dataIndex: "fees",
                render: (v) => formatKrw(num(v), 2),
              },
              {
                title: "Net",
                dataIndex: "net_pnl",
                render: (v) => (
                  <span style={{ color: pnlColor(num(v)) }}>
                    {formatKrw(num(v), 2)}
                  </span>
                ),
              },
              {
                title: "Return",
                dataIndex: "return_pct",
                render: (v) => formatPct(num(v)),
              },
              {
                title: "Holding",
                dataIndex: "duration_sec",
                render: (v) => durationLabel(num(v) ?? undefined),
              },
              { title: "Exit", dataIndex: "exit_reason_label_ko" },
              { title: "Closed", dataIndex: "closed_at", ellipsis: true },
            ]}
          />
        )}
      </Card>

      <SymbolPerformanceDrawer
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setDrawerSymbol(null);
        }}
        symbol={drawerSymbol}
        broker={broker}
        period={applied.period}
        startDate={applied.start}
        endDate={applied.end}
        userBrokerAccountId={userBrokerAccountId}
      />
    </Space>
  );
}
