"use client";

import { useQuery } from "@tanstack/react-query";

import { getMobileOverview } from "@/features/mobile/mobileApi";
import { queryKeys } from "@/lib/query/queryKeys";

export function useMobileOverview(refetchMs = 15_000) {
  return useQuery({
    queryKey: queryKeys.mobile.overview(),
    queryFn: getMobileOverview,
    refetchInterval: refetchMs,
    staleTime: 10_000,
    refetchOnWindowFocus: true,
    retry: 1,
  });
}
