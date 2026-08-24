/**
 * 전략·분석 공통 시장 범위.
 * URL ?market=ALL|KIWOOM|UPBIT — 내부 enum 유지, UI는 한글.
 */

export const STRATEGY_MARKETS = ["ALL", "KIWOOM", "UPBIT"] as const;

export type StrategyMarket = (typeof STRATEGY_MARKETS)[number];

export const STRATEGY_MARKET_LABEL_KO: Record<StrategyMarket, string> = {
  ALL: "전체",
  KIWOOM: "키움",
  UPBIT: "업비트",
};

export function parseStrategyMarket(
  raw: string | null | undefined,
): StrategyMarket {
  const u = String(raw ?? "")
    .trim()
    .toUpperCase();
  if (u === "KIWOOM" || u === "KRX" || u === "KR") return "KIWOOM";
  if (u === "UPBIT" || u === "CRYPTO" || u === "KRW") return "UPBIT";
  if (u === "ALL") return "ALL";
  return "ALL";
}

export function strategyMarketQuery(market: StrategyMarket): string {
  return market === "ALL" ? "" : `market=${market}`;
}

export function withMarketQuery(
  href: string,
  market: StrategyMarket,
): string {
  if (market === "ALL") return href;
  const sep = href.includes("?") ? "&" : "?";
  return `${href}${sep}market=${market}`;
}

/** CLEAN Forward 등은 UPBIT 전용 — KIWOOM과 합산 금지 */
export function isUpbitOnlyResearch(market: StrategyMarket): boolean {
  return market === "UPBIT" || market === "ALL";
}

export function isKiwoomVisible(market: StrategyMarket): boolean {
  return market === "KIWOOM" || market === "ALL";
}

export function isUpbitVisible(market: StrategyMarket): boolean {
  return market === "UPBIT" || market === "ALL";
}
