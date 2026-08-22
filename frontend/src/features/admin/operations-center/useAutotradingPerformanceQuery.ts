"use client";

import { useQuery } from "@tanstack/react-query";

import * as adminApi from "@/features/admin/api/adminApi";
import { queryKeys } from "@/lib/query/queryKeys";

import type { BrokerFilter, PeriodFilter } from "./autoTradingPerformanceHelpers";

type Options = {
  broker: BrokerFilter;
  period: PeriodFilter;
  enabled?: boolean;
  includeOps?: boolean;
  refreshMs?: number;
};

export function useAutotradingPerformanceQuery({
  broker,
  period,
  enabled = true,
  includeOps = false,
  refreshMs = 60_000,
}: Options) {
  return useQuery({
    queryKey: queryKeys.admin.autotradingPerformance({
      broker,
      period,
      includeOps,
    }),
    queryFn: () =>
      adminApi.getAdminAutotradingPerformance({
        broker,
        period,
        include_ops: includeOps,
      }),
    enabled,
    refetchInterval: enabled && refreshMs > 0 ? refreshMs : false,
    staleTime: 45_000,
    placeholderData: (prev) => prev,
  });
}
