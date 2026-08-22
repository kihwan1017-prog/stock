/**
 * Compact Dashboard — 탭/필터 URL 상태 (V2).
 */

export type DashboardTab = "summary" | "performance" | "operations";

export type PerformanceChartType =
  | "cumulative_pnl"
  | "daily_pnl"
  | "cumulative_return"
  | "symbol_pnl"
  | "symbol_return"
  | "win_loss"
  | "exit_reason"
  | "trade_pnl"
  | "holding_return"
  | "broker_compare";

export type BrokerFilter = "ALL" | "UPBIT" | "KIWOOM";
export type PeriodFilter = "TODAY" | "7D" | "30D" | "90D" | "ALL";
export type SummaryPeriodFilter = "7D" | "30D" | "90D";

export const DASHBOARD_TABS: { key: DashboardTab; label: string }[] = [
  { key: "summary", label: "요약" },
  { key: "performance", label: "성과 분석" },
  { key: "operations", label: "운영 현황" },
];

export const BROKER_SEGMENTS: { label: string; value: BrokerFilter }[] = [
  { label: "전체", value: "ALL" },
  { label: "업비트", value: "UPBIT" },
  { label: "키움증권", value: "KIWOOM" },
];

export const PERIOD_OPTIONS: { label: string; value: PeriodFilter }[] = [
  { label: "오늘", value: "TODAY" },
  { label: "7일", value: "7D" },
  { label: "30일", value: "30D" },
  { label: "90일", value: "90D" },
  { label: "전체", value: "ALL" },
];

export const SUMMARY_PERIOD_OPTIONS: { label: string; value: SummaryPeriodFilter }[] =
  [
    { label: "7일", value: "7D" },
    { label: "30일", value: "30D" },
    { label: "90일", value: "90D" },
  ];

export const CHART_OPTIONS: { label: string; value: PerformanceChartType }[] = [
  { label: "누적 실현손익", value: "cumulative_pnl" },
  { label: "일별 실현손익", value: "daily_pnl" },
  { label: "누적 수익률", value: "cumulative_return" },
  { label: "종목별 실현손익", value: "symbol_pnl" },
  { label: "종목별 수익률", value: "symbol_return" },
  { label: "승/패 비율", value: "win_loss" },
  { label: "Exit Reason", value: "exit_reason" },
  { label: "거래별 손익", value: "trade_pnl" },
  { label: "보유시간 vs 수익률", value: "holding_return" },
  { label: "거래소 비교", value: "broker_compare" },
];

const TAB_SET = new Set(DASHBOARD_TABS.map((t) => t.key));
const CHART_SET = new Set(CHART_OPTIONS.map((c) => c.value));
const BROKER_SET = new Set(BROKER_SEGMENTS.map((b) => b.value));
const PERIOD_SET = new Set(PERIOD_OPTIONS.map((p) => p.value));
const SUMMARY_PERIOD_SET = new Set(SUMMARY_PERIOD_OPTIONS.map((p) => p.value));

export type DashboardUrlState = {
  tab: DashboardTab;
  broker: BrokerFilter;
  period: PeriodFilter;
  summaryPeriod: SummaryPeriodFilter;
  chart: PerformanceChartType;
};

export function parseDashboardUrlState(
  params: URLSearchParams,
): DashboardUrlState {
  const tabRaw = params.get("tab") ?? "summary";
  const brokerRaw = (params.get("broker") ?? "ALL").toUpperCase();
  const periodRaw = (params.get("period") ?? "30D").toUpperCase();
  const summaryPeriodRaw = (params.get("summaryPeriod") ?? "30D").toUpperCase();
  const chartRaw = params.get("chart") ?? "cumulative_pnl";

  return {
    tab: TAB_SET.has(tabRaw) ? (tabRaw as DashboardTab) : "summary",
    broker: BROKER_SET.has(brokerRaw)
      ? (brokerRaw as BrokerFilter)
      : "ALL",
    period: PERIOD_SET.has(periodRaw)
      ? (periodRaw as PeriodFilter)
      : "30D",
    summaryPeriod: SUMMARY_PERIOD_SET.has(summaryPeriodRaw)
      ? (summaryPeriodRaw as SummaryPeriodFilter)
      : "30D",
    chart: CHART_SET.has(chartRaw)
      ? (chartRaw as PerformanceChartType)
      : "cumulative_pnl",
  };
}

export function buildDashboardSearchParams(
  state: Partial<DashboardUrlState>,
  current: DashboardUrlState,
): URLSearchParams {
  const next: DashboardUrlState = { ...current, ...state };
  const p = new URLSearchParams();
  p.set("tab", next.tab);
  p.set("broker", next.broker);
  if (next.tab === "summary") {
    p.set("summaryPeriod", next.summaryPeriod);
  }
  if (next.tab === "performance") {
    p.set("period", next.period);
    p.set("chart", next.chart);
  }
  return p;
}
