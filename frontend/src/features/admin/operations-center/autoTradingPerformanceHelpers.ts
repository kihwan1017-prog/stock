/**
 * AUTO trading performance dashboard — API 응답 파싱/표시 헬퍼.
 */

import { asRecord } from "@/features/admin/utils/dataHelpers";

export type BrokerFilter = "ALL" | "UPBIT" | "KIWOOM";
export type PeriodFilter = "TODAY" | "7D" | "30D" | "90D" | "ALL";

export type PerformanceSummary = {
  todayRealizedPnl: number | null;
  todayReturnPct: number | null;
  periodRealizedPnl: number | null;
  periodNetPnl: number | null;
  periodGrossPnl: number | null;
  periodFees: number | null;
  periodProfitFactor: string | null;
  periodReturnPct: number | null;
  cumulativeRealizedPnl: number | null;
  cumulativeReturnPct: number | null;
  currentUnrealizedPnl: number | null;
  winRatePct: number | null;
  closedTradeCount: number;
  openPositionCount: number;
  avgTradeReturnPct: number | null;
};

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function int(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : 0;
}

export function parsePerformanceSummary(raw: unknown): PerformanceSummary {
  const s = asRecord(raw) ?? {};
  const periodNet = num(s.period_net_pnl ?? s.period_realized_pnl);
  return {
    todayRealizedPnl: num(s.today_realized_pnl),
    todayReturnPct: num(s.today_return_pct),
    periodRealizedPnl: periodNet,
    periodNetPnl: periodNet,
    periodGrossPnl: num(s.period_gross_pnl),
    periodFees: num(s.period_fees),
    periodProfitFactor:
      s.period_profit_factor == null || s.period_profit_factor === ""
        ? null
        : String(s.period_profit_factor),
    periodReturnPct: num(s.period_return_pct),
    cumulativeRealizedPnl: num(s.cumulative_realized_pnl),
    cumulativeReturnPct: num(s.cumulative_return_pct),
    currentUnrealizedPnl: num(s.current_unrealized_pnl),
    winRatePct: num(s.win_rate_pct),
    closedTradeCount: int(s.closed_trade_count),
    openPositionCount: int(s.open_position_count),
    avgTradeReturnPct: num(s.avg_trade_return_pct),
  };
}

export function formatKrw(value: number | null, digits = 0): string {
  if (value == null) return "—";
  return `${value.toLocaleString("ko-KR", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })}원`;
}

export function formatPct(value: number | null, digits = 2): string {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function pnlColor(value: number | null): string | undefined {
  if (value == null || value === 0) return undefined;
  return value > 0 ? "#3f8600" : "#cf1322";
}

export function durationLabel(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}시간 ${m}분`;
  if (m > 0) return `${m}분 ${s}초`;
  return `${s}초`;
}

export const BROKER_FILTER_OPTIONS: { label: string; value: BrokerFilter }[] = [
  { label: "전체", value: "ALL" },
  { label: "업비트", value: "UPBIT" },
  { label: "키움", value: "KIWOOM" },
];

export const PERIOD_FILTER_OPTIONS: { label: string; value: PeriodFilter }[] = [
  { label: "오늘", value: "TODAY" },
  { label: "7일", value: "7D" },
  { label: "30일", value: "30D" },
  { label: "90일", value: "90D" },
  { label: "전체", value: "ALL" },
];

/** UI 기간 프리셋 (직접 선택은 custom) */
export type DatePreset = "TODAY" | "YESTERDAY" | "7D" | "30D" | "CUSTOM";

export const DATE_PRESET_OPTIONS: { label: string; value: DatePreset }[] = [
  { label: "오늘", value: "TODAY" },
  { label: "어제", value: "YESTERDAY" },
  { label: "최근 7일", value: "7D" },
  { label: "최근 30일", value: "30D" },
  { label: "직접 선택", value: "CUSTOM" },
];

export const MAX_PERFORMANCE_RANGE_DAYS = 90;

export function isSingleDayPeriod(start: string | null, end: string | null): boolean {
  return Boolean(start && end && start === end);
}
