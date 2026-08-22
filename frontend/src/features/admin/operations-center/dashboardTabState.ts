/**
 * Compact Dashboard — 탭/필터 URL 상태.
 */

export type DashboardTab = "summary" | "performance" | "operations";

export type PerformanceChartType =
  | "daily"
  | "cumulative"
  | "symbol"
  | "exit_reason"
  | "distribution";

export type BrokerFilter = "ALL" | "UPBIT" | "KIWOOM";
export type PeriodFilter = "TODAY" | "7D" | "30D" | "ALL";

export const DASHBOARD_TABS: { key: DashboardTab; label: string }[] = [
  { key: "summary", label: "요약" },
  { key: "performance", label: "성과 분석" },
  { key: "operations", label: "운영 현황" },
];

export const CHART_SEGMENTS: { label: string; value: PerformanceChartType }[] =
  [
    { label: "일별", value: "daily" },
    { label: "누적", value: "cumulative" },
    { label: "종목별", value: "symbol" },
    { label: "청산유형", value: "exit_reason" },
    { label: "분포", value: "distribution" },
  ];

const TAB_SET = new Set<string>(DASHBOARD_TABS.map((t) => t.key));
const CHART_SET = new Set<string>(CHART_SEGMENTS.map((c) => c.value));
const BROKER_SET = new Set<string>(["ALL", "UPBIT", "KIWOOM"]);
const PERIOD_SET = new Set<string>(["TODAY", "7D", "30D", "ALL"]);

export type DashboardUrlState = {
  tab: DashboardTab;
  broker: BrokerFilter;
  period: PeriodFilter;
  chart: PerformanceChartType;
};

export function parseDashboardUrlState(
  params: URLSearchParams,
): DashboardUrlState {
  const tabRaw = params.get("tab") ?? "summary";
  const brokerRaw = (params.get("broker") ?? "ALL").toUpperCase();
  const periodRaw = (params.get("period") ?? "30D").toUpperCase();
  const chartRaw = params.get("chart") ?? "daily";

  return {
    tab: TAB_SET.has(tabRaw) ? (tabRaw as DashboardTab) : "summary",
    broker: BROKER_SET.has(brokerRaw)
      ? (brokerRaw as BrokerFilter)
      : "ALL",
    period: PERIOD_SET.has(periodRaw)
      ? (periodRaw as PeriodFilter)
      : "30D",
    chart: CHART_SET.has(chartRaw)
      ? (chartRaw as PerformanceChartType)
      : "daily",
  };
}

export function buildDashboardSearchParams(
  state: Partial<DashboardUrlState>,
  current: DashboardUrlState,
): URLSearchParams {
  const next: DashboardUrlState = { ...current, ...state };
  const p = new URLSearchParams();
  p.set("tab", next.tab);
  if (next.tab === "performance") {
    p.set("broker", next.broker);
    p.set("period", next.period);
    p.set("chart", next.chart);
  }
  return p;
}
