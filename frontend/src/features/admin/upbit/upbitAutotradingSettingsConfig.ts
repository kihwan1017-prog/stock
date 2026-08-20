/**
 * UPBIT 자동매매 설정 워크스페이스 — 탭 키·보수 기본값·모드 표시 헬퍼.
 * PORTFOLIO Enable / REAL 주문은 여기서 수행하지 않음.
 */

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
  market: "전체시장 자동선정",
  capital: "자금 · 포지션",
  entry: "진입 규칙",
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
