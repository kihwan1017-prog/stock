/** 보유자산 행 PnL 계산 — 0원 vs 데이터 없음 구분 */

import {
  isEffectivelyZero,
  parseDecimalSafe,
} from "@/shared/utils/numericFormatKo";

export type MarketFilter = "ALL" | "UPBIT" | "KIWOOM";
export type DataQuality =
  | "OK"
  | "AVG_PRICE_MISSING"
  | "PRICE_PENDING"
  | "BROKER_SNAPSHOT"
  | "STRATEGY_BINDING"
  | "COMPUTED_VALUATION";

export type HoldingMetricsInput = {
  quantity: unknown;
  brokerAvgPrice: unknown;
  autoEntryPrice: unknown;
  currentPrice: unknown;
  brokerEvalAmount: unknown;
  brokerUnrealized: unknown;
  brokerPurchaseAmount: unknown;
  owner: string;
};

export type HoldingMetrics = {
  quantity: number | null;
  avgPrice: number | null;
  avgPriceMissing: boolean;
  currentPrice: number | null;
  purchaseAmount: number | null;
  valuationAmount: number | null;
  unrealizedPnl: number | null;
  returnPct: number | null;
  dataQuality: DataQuality;
  avgPriceSource: string;
  valuationSource: string;
  unrealizedSource: string;
};

export function resolveHoldingMetrics(input: HoldingMetricsInput): HoldingMetrics {
  const qty = parseDecimalSafe(input.quantity);
  const brokerAvg = parseDecimalSafe(input.brokerAvgPrice);
  const autoEntry = parseDecimalSafe(input.autoEntryPrice);
  const cur = parseDecimalSafe(input.currentPrice);
  const brokerEval = parseDecimalSafe(input.brokerEvalAmount);
  const brokerUnreal = parseDecimalSafe(input.brokerUnrealized);
  const brokerPurchase = parseDecimalSafe(input.brokerPurchaseAmount);
  const owner = String(input.owner || "").toUpperCase();

  let avg: number | null = null;
  let avgSource = "NONE";
  if (owner === "AUTO" && autoEntry != null && autoEntry > 0) {
    avg = autoEntry;
    avgSource = "STRATEGY_BINDING_ENTRY";
  } else if (brokerAvg != null && brokerAvg > 0) {
    avg = brokerAvg;
    avgSource = "BROKER_SNAPSHOT";
  }

  const avgMissing = avg == null;
  let valuation: number | null = null;
  let valuationSource = "NONE";
  if (
    brokerEval != null &&
    brokerEval > 0 &&
    qty != null &&
    !isEffectivelyZero(qty)
  ) {
    // broker qty와 표시 qty가 어긋나면 재계산 우선
    const brokerQtyImplied =
      cur != null && cur > 0 ? brokerEval / cur : null;
    if (
      brokerQtyImplied != null &&
      qty != null &&
      Math.abs(brokerQtyImplied - qty) / Math.max(qty, 1e-12) < 0.05
    ) {
      valuation = brokerEval;
      valuationSource = "BROKER_SNAPSHOT";
    }
  }
  if (valuation == null && qty != null && cur != null && cur > 0 && qty > 0) {
    valuation = qty * cur;
    valuationSource = "QTY_X_CURRENT";
  }

  let purchase: number | null = null;
  if (brokerPurchase != null && brokerPurchase > 0 && avgSource === "BROKER_SNAPSHOT") {
    purchase = brokerPurchase;
  } else if (qty != null && avg != null && qty > 0) {
    purchase = qty * avg;
  }

  let unrealized: number | null = null;
  let unrealizedSource = "NONE";
  if (
    !avgMissing &&
    valuation != null &&
    purchase != null &&
    purchase > 0
  ) {
    unrealized = valuation - purchase;
    unrealizedSource = "VALUATION_MINUS_COST";
  } else if (
    avgSource === "BROKER_SNAPSHOT" &&
    brokerUnreal != null &&
    valuationSource === "BROKER_SNAPSHOT"
  ) {
    unrealized = brokerUnreal;
    unrealizedSource = "BROKER_SNAPSHOT";
  }

  let returnPct: number | null = null;
  if (unrealized != null && purchase != null && purchase > 0) {
    returnPct = (unrealized / purchase) * 100;
  }

  let quality: DataQuality = "OK";
  if (qty != null && qty > 0 && cur == null) quality = "PRICE_PENDING";
  else if (qty != null && qty > 0 && avgMissing) quality = "AVG_PRICE_MISSING";
  else if (valuationSource === "QTY_X_CURRENT") quality = "COMPUTED_VALUATION";
  else if (avgSource === "STRATEGY_BINDING_ENTRY") quality = "STRATEGY_BINDING";
  else if (avgSource === "BROKER_SNAPSHOT") quality = "BROKER_SNAPSHOT";

  return {
    quantity: qty,
    avgPrice: avg,
    avgPriceMissing: avgMissing,
    currentPrice: cur,
    purchaseAmount: purchase,
    valuationAmount: valuation,
    unrealizedPnl: unrealized,
    returnPct,
    dataQuality: quality,
    avgPriceSource: avgSource,
    valuationSource,
    unrealizedSource,
  };
}

export function dataQualityLabelKo(q: DataQuality): string {
  switch (q) {
    case "OK":
      return "정상";
    case "AVG_PRICE_MISSING":
      return "평균단가 없음";
    case "PRICE_PENDING":
      return "가격 확인 중";
    case "BROKER_SNAPSHOT":
      return "Broker snapshot";
    case "STRATEGY_BINDING":
      return "자동매매 position";
    case "COMPUTED_VALUATION":
      return "평가 재계산";
    default:
      return "확인 필요";
  }
}

export function formatOptionalKrw(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "확인 불가";
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

export function formatOptionalPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatOptionalPnl(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "계산 불가";
  const sign = value > 0 ? "+" : "";
  return `${sign}${Math.round(value).toLocaleString("ko-KR")}원`;
}

export function assetDisplayName(
  symbol: string,
  name: string | null | undefined,
  broker: string,
): string {
  const sym = String(symbol || "").trim();
  const n = String(name || "").trim();
  if (!n || n.toUpperCase() === sym.toUpperCase()) return sym;
  if (broker === "KIWOOM") return `${n} (${sym})`;
  // UPBIT: SUI / KRW-SUI
  const short = sym.includes("-") ? sym.split("-").slice(1).join("-") : sym;
  if (n.toUpperCase() === short.toUpperCase()) return `${n}\n${sym}`;
  return `${n}\n${sym}`;
}
