"use client";

import { PeriodPerformanceAnalyticsPanel } from "./PeriodPerformanceAnalyticsPanel";
import type { BrokerFilter, PeriodFilter } from "./autoTradingPerformanceHelpers";
import type { PerformanceChartType } from "./dashboardTabState";

type Props = {
  enabled: boolean;
  broker: BrokerFilter;
  period: PeriodFilter;
  chart: PerformanceChartType;
  onPeriodChange: (v: PeriodFilter) => void;
  onChartChange: (v: PerformanceChartType) => void;
  refreshMs?: number;
};

/**
 * Ops Center 성과 탭 — 기간 검색/종목표/Drawer 통합 패널 재사용.
 * URL period/chart props는 상위 호환용으로 수신하되, 조회는 패널 내부 기간 상태가 SoT.
 */
export function DashboardPerformanceTab({
  enabled,
  broker,
  period: _period,
  chart: _chart,
  onPeriodChange: _onPeriodChange,
  onChartChange: _onChartChange,
  refreshMs = 60_000,
}: Props) {
  return (
    <PeriodPerformanceAnalyticsPanel
      broker={broker}
      enabled={enabled}
      refreshMs={refreshMs}
      defaultPreset="TODAY"
      showChartSelector
    />
  );
}
