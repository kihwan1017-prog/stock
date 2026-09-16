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
  startDate?: string | null;
  endDate?: string | null;
  userBrokerAccountId?: number | null;
};

export function useAutotradingPerformanceQuery({
  broker,
  period,
  enabled = true,
  includeOps = false,
  refreshMs = 60_000,
  startDate = null,
  endDate = null,
  userBrokerAccountId = null,
}: Options) {
  return useQuery({
    queryKey: queryKeys.admin.autotradingPerformance({
      broker,
      period,
      includeOps,
      startDate: startDate ?? null,
      endDate: endDate ?? null,
      ubaId: userBrokerAccountId ?? null,
    }),
    queryFn: () =>
      adminApi.getAdminAutotradingPerformance({
        broker,
        period,
        include_ops: includeOps,
        start_date: startDate ?? undefined,
        end_date: endDate ?? undefined,
        user_broker_account_id: userBrokerAccountId ?? undefined,
      }),
    enabled,
    refetchInterval: enabled && refreshMs > 0 ? refreshMs : false,
    staleTime: 45_000,
    placeholderData: (prev) => prev,
  });
}
