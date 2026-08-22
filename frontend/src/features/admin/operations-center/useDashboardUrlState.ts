"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import {
  buildDashboardSearchParams,
  parseDashboardUrlState,
  type DashboardTab,
  type DashboardUrlState,
  type PerformanceChartType,
} from "./dashboardTabState";
import type { BrokerFilter, PeriodFilter } from "./autoTradingPerformanceHelpers";

export function useDashboardUrlState() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const state = useMemo(
    () => parseDashboardUrlState(searchParams),
    [searchParams],
  );

  const patch = useCallback(
    (partial: Partial<DashboardUrlState>) => {
      const next = buildDashboardSearchParams(partial, state);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [pathname, router, state],
  );

  return {
    ...state,
    setTab: (tab: DashboardTab) => patch({ tab }),
    setBroker: (broker: BrokerFilter) => patch({ broker, tab: "performance" }),
    setPeriod: (period: PeriodFilter) => patch({ period, tab: "performance" }),
    setChart: (chart: PerformanceChartType) => patch({ chart, tab: "performance" }),
  };
}
