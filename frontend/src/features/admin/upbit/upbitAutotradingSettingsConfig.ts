/**
 * UPBIT 자동매매 설정 워크스페이스 — 탭 키·보수 기본값·모드 표시 헬퍼.
 * PORTFOLIO Enable / REAL 주문은 여기서 수행하지 않음.
 */

import { asRecord } from "@/shared/utils/dataHelpers";

export const UPBIT_AUTOTRADING_TAB_KEYS = {
  market: "market",
  capital: "capital",
  entry: "entry",
  exit: "exit",
  ai: "ai",
  safety: "safety",
} as const;

export type UpbitAutotradingTabKey =
  (typeof UPBIT_AUTOTRADING_TAB_KEYS)[keyof typeof UPBIT_AUTOTRADING_TAB_KEYS];

export const UPBIT_AUTOTRADING_TAB_ORDER: readonly UpbitAutotradingTabKey[] = [
  UPBIT_AUTOTRADING_TAB_KEYS.market,
  UPBIT_AUTOTRADING_TAB_KEYS.capital,
  UPBIT_AUTOTRADING_TAB_KEYS.entry,
  UPBIT_AUTOTRADING_TAB_KEYS.exit,
  UPBIT_AUTOTRADING_TAB_KEYS.ai,
  UPBIT_AUTOTRADING_TAB_KEYS.safety,
] as const;

export const UPBIT_AUTOTRADING_TAB_LABELS: Record<
  UpbitAutotradingTabKey,
  string
> = {
  market: "현황",
  capital: "자금 · 포지션",
  entry: "진입 · 후보 정책",
  exit: "청산 규칙",
  ai: "AI",
  safety: "안전 · 손실 제한",
};

/** 폼에만 채우는 보수적 기본값 (자동 저장·Enable 없음) */
export const CONSERVATIVE_PORTFOLIO_DEFAULTS = {
  max_positions: 3,
  portfolio_capital_limit_krw: 500_000,
  per_position_target_pct: 0.08,
  max_symbol_exposure_pct: 0.12,
  max_total_exposure_pct: 0.3,
  min_cash_reserve_pct: 0.6,
  portfolio_max_pending_entries: 1,
  allow_averaging_down: false,
  allow_duplicate_symbol: false,
  entry_cooldown_seconds: 300,
  candidate_max_age_seconds: 1800,
  candidate_hold_seconds: 1800,
  candidate_max_wait_seconds: 10800,
  candidate_switch_min_score_delta: 8,
  portfolio_daily_entry_limit: 10,
  daily_loss_limit_pct: 0.02,
  consecutive_loss_limit: 3,
} as const;

export type ConservativePortfolioDefaults =
  typeof CONSERVATIVE_PORTFOLIO_DEFAULTS;

/** FIXED / SINGLE / PORTFOLIO 표시용 */
export function formatUpbitAutotradingModeLabel(mode: unknown): string {
  const raw = String(mode ?? "FIXED_SYMBOL").toUpperCase();
  if (raw === "FULL_MARKET_PORTFOLIO" || raw === "PORTFOLIO") {
    return "PORTFOLIO";
  }
  if (
    raw === "FULL_MARKET_SINGLE" ||
    raw === "FULL_MARKET_AUTO" ||
    raw === "SINGLE"
  ) {
    return "SINGLE";
  }
  return "FIXED";
}

export function isPortfolioMode(mode: unknown): boolean {
  return formatUpbitAutotradingModeLabel(mode) === "PORTFOLIO";
}

export function isFullMarketSingleMode(mode: unknown): boolean {
  return formatUpbitAutotradingModeLabel(mode) === "SINGLE";
}

export const DEFAULT_UPBIT_AUTOTRADING_UBA_ID = 1380;

/** portfolio / full-market / ops 응답이 null·로딩 중이어도 crash 없이 strategy_id 추출 */
export function resolveStrategyIdFromSources(sources: {
  portfolio?: unknown;
  fullMarket?: unknown;
  ops?: unknown;
}): number | null {
  const portfolio = asRecord(sources.portfolio) ?? {};
  const fullMarket = asRecord(sources.fullMarket) ?? {};
  const ops = asRecord(sources.ops) ?? {};
  const raw = portfolio.strategy_id ?? fullMarket.strategy_id ?? ops.strategy_id;
  if (raw == null || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : null;
}

/** UI Empty State 라벨 (AUTO 보유 0·전략 미연결 등 정상 운영) */
export const UPBIT_AUTOTRADING_EMPTY_LABELS = {
  noStrategy: "연결된 전략 없음",
  noAutoPositions: "현재 AUTO 보유 종목 없음",
  noSlots: "대기 슬롯 없음",
  noLatestEntry: "최근 진입 없음",
} as const;

/** Backend confirmation phrases (audit gate) */
export const CONFIRM_ENABLE_PORTFOLIO = "전체시장 포트폴리오 모드 시작";
export const CONFIRM_DISABLE_PORTFOLIO = "전체시장 포트폴리오 모드 중지";

export type PortfolioEnableGateInput = {
  portfolioOn: boolean;
  live?: string | null;
  arm?: string | null;
  unattendedEnabled?: boolean;
  unattendedRemainingSeconds?: number;
  primaryBlocker?: string | null;
  killActive?: boolean;
  conflictHighCritical?: number;
};

/**
 * Enable 버튼은 항상 노출. 불가 시 disabled + reason.
 * (숨기지 않음)
 */
export function resolvePortfolioEnableControl(input: PortfolioEnableGateInput): {
  showEnable: boolean;
  showDisable: boolean;
  enableDisabled: boolean;
  disableReasons: string[];
} {
  if (input.portfolioOn) {
    return {
      showEnable: false,
      showDisable: true,
      enableDisabled: true,
      disableReasons: [],
    };
  }
  const reasons: string[] = [];
  if (String(input.live ?? "OFF").toUpperCase() !== "ON") {
    reasons.push("LIVE_OFF");
  }
  if (String(input.arm ?? "OFF").toUpperCase() !== "ON") {
    reasons.push("ARM_OFF");
  }
  if (!input.unattendedEnabled) {
    reasons.push("UNATTENDED_OFF");
  } else if (
    input.unattendedRemainingSeconds != null &&
    Number(input.unattendedRemainingSeconds) < 60
  ) {
    reasons.push("UNATTENDED_EXPIRING");
  }
  if (input.killActive) {
    reasons.push("KILL_SWITCH");
  }
  const blocker = String(input.primaryBlocker ?? "").toUpperCase();
  if (blocker && blocker !== "NONE" && blocker !== "NULL") {
    // LIVE/ARM은 위에서 이미 집계 — 중복 아닌 추가 blocker만
    if (
      !blocker.includes("LIVE_OFF") &&
      !blocker.includes("ARM_OFF") &&
      !reasons.includes(blocker)
    ) {
      reasons.push(blocker);
    }
  }
  if (
    input.conflictHighCritical != null &&
    Number(input.conflictHighCritical) > 0
  ) {
    reasons.push("CONFLICT_HIGH_CRITICAL");
  }
  return {
    showEnable: true,
    showDisable: false,
    enableDisabled: reasons.length > 0,
    disableReasons: reasons,
  };
}
