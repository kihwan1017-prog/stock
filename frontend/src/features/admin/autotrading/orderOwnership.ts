/**
 * 주문 AUTO/MANUAL 판별.
 *
 * 현재 GET /orders 는 strategy_code만 노출하고 strategy_id·order_source는 미노출
 * (BACKEND_READ_API_GAP). strategy_id null만으로 오판하지 않도록
 * 가용 필드를 조합하고 confidence를 붙인다.
 */

export type OrderTradingKind = "AUTO" | "MANUAL" | "UNKNOWN";

export type OrderOwnershipHint = {
  kind: OrderTradingKind;
  labelKo: string;
  /** high = 비교적 확실, low = 추정 */
  confidence: "high" | "low" | "none";
  reason: string;
};

function hasText(v: unknown): boolean {
  return v != null && String(v).trim() !== "";
}

/**
 * Provenance 휴리스틱 (백엔드 strategy_id 노출 전 임시).
 * - strategy_code 또는 strategy_id 존재 → AUTO
 * - execution_mode=MANUAL 명시 → MANUAL
 * - strategy_* 없고 수동 메타 → MANUAL
 * - 그 외 → UNKNOWN (일반매매로 단정하지 않음)
 */
export function resolveOrderTradingKind(
  row: Record<string, unknown> | null | undefined,
): OrderOwnershipHint {
  if (!row) {
    return {
      kind: "UNKNOWN",
      labelKo: "확인 필요",
      confidence: "none",
      reason: "empty_row",
    };
  }

  const exec = String(row.execution_mode ?? "").toUpperCase();
  const source = String(row.order_source ?? row.source ?? "").toUpperCase();
  const strategyId = row.strategy_id;
  const strategyCode = row.strategy_code;

  if (exec === "MANUAL" || source === "MANUAL") {
    return {
      kind: "MANUAL",
      labelKo: "일반매매",
      confidence: "high",
      reason: "execution_mode_or_source_manual",
    };
  }

  if (
    (strategyId != null && String(strategyId).trim() !== "") ||
    hasText(strategyCode)
  ) {
    return {
      kind: "AUTO",
      labelKo: "자동매매",
      confidence: strategyId != null ? "high" : "low",
      reason:
        strategyId != null ? "strategy_id_present" : "strategy_code_present",
    };
  }

  if (exec === "LIVE" || exec === "PAPER" || exec === "SHADOW") {
    return {
      kind: "UNKNOWN",
      labelKo: "확인 필요",
      confidence: "none",
      reason: "execution_mode_without_strategy",
    };
  }

  // strategy 메타 전무 → 일반매매로 표시하되 low confidence
  return {
    kind: "MANUAL",
    labelKo: "일반매매",
    confidence: "low",
    reason: "no_strategy_meta_assumed_manual",
  };
}

export function orderTradingKindMatchesFilter(
  hint: OrderOwnershipHint,
  filter: "ALL" | OrderTradingKind,
): boolean {
  if (filter === "ALL") return true;
  return hint.kind === filter;
}
