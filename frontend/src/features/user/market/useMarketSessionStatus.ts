"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord } from "@/shared/utils/dataHelpers";
import { queryKeys } from "@/lib/query/queryKeys";

import {
  getSessionPhaseMessage,
  type SessionPhaseMessage,
} from "./sessionPhaseMessages";

export interface MarketSessionStatus {
  exchange_code: string;
  calendar_date: string;
  is_trading_day: boolean;
  session_type: string | null;
  is_special_session: boolean;
  regular_open_at: string | null;
  regular_close_at: string | null;
  holiday_name: string | null;
  closure_reason: string | null;
  next_trading_day: string | null;
  calendar_available: boolean;
  status_message: string;
  phase: string | null;
  new_entry_cutoff_at: string | null;
  next_transition_at: string | null;
  next_transition_phase: string | null;
  is_delayed_open: boolean;
  is_early_close: boolean;
  new_entry_allowed: boolean;
  risk_reducing_allowed: boolean;
  // STEP 8-5-15 — 영속 Market Session Job 기반 소프트 상태 (Job ID 미노출)
  snapshot_ready: boolean;
  analysis_ready: boolean;
}

export interface UseMarketSessionStatusResult {
  query: UseQueryResult<unknown, unknown>;
  status: MarketSessionStatus | null;
  phaseMessage: SessionPhaseMessage;
}

/**
 * STEP 8-5-13 — `/user/market-calendar/status` 하나의 소스로 KRX Session
 * Phase를 조회하는 공용 Hook. Dashboard·전략·주문 화면이 각자 시간 계산을
 * 중복 구현하지 않도록 이 Hook + `sessionPhaseMessages`만 재사용한다.
 */
export function useMarketSessionStatus(
  exchangeCode = "KRX",
): UseMarketSessionStatusResult {
  const query = useQuery({
    queryKey: queryKeys.user.marketSessionStatus(exchangeCode),
    queryFn: () => adminApi.getUserMarketCalendarStatus(exchangeCode),
    refetchInterval: 60_000,
  });

  const status = asRecord(query.data) as MarketSessionStatus | null;
  const phaseMessage = getSessionPhaseMessage(status?.phase ?? null);

  return { query, status, phaseMessage };
}
