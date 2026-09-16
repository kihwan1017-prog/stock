/** Symbol ownership UI labels — KIWOOM/UPBIT 공통 */

export type SymbolOwner =
  | "MANUAL"
  | "AUTO"
  | "FREE"
  | "UNKNOWN"
  | "AUTO_EXCLUDED";

export function ownershipLabelKo(owner: string | null | undefined): string {
  switch ((owner || "").toUpperCase()) {
    case "MANUAL":
      return "일반매매";
    case "AUTO":
      return "자동매매";
    case "FREE":
      return "후보 가능";
    case "AUTO_EXCLUDED":
      return "자동매매 제외";
    case "UNKNOWN":
      return "확인 필요";
    default:
      return "미분류";
  }
}

export function ownershipExcludeReasonKo(
  reasons: string[] | null | undefined,
): string | null {
  const set = new Set((reasons || []).map((r) => r.toUpperCase()));
  if (set.has("MANUAL_POSITION")) return "일반매매 보유 중";
  if (set.has("MANUAL_OPEN_ORDER")) return "일반 미체결 주문 존재";
  if (set.has("AUTO_EXCLUDED_BY_USER")) return "사용자가 자동매매 제외";
  if (set.has("SAME_SYMBOL_MANUAL_AUTO_MIX"))
    return "자동/일반매매 충돌";
  if (set.has("AUTO_BINDING") || set.has("AUTO_SLOT"))
    return "자동매매 관리 중";
  return null;
}

/** Ant Design Tag color */
export function ownershipBadgeColor(
  owner: string | null | undefined,
): string {
  switch ((owner || "").toUpperCase()) {
    case "MANUAL":
      return "default";
    case "AUTO":
      return "processing";
    case "AUTO_EXCLUDED":
      return "warning";
    case "FREE":
      return "cyan";
    case "UNKNOWN":
      return "error";
    default:
      return "default";
  }
}

/** 보유자산 목록 필터 — FREE는 수량 0 후보라 기본 숨김 */
export type HoldingsOwnerFilter = "ALL" | "MANUAL" | "AUTO";

export function ownershipMatchesHoldingsFilter(
  owner: string | null | undefined,
  filter: HoldingsOwnerFilter,
): boolean {
  const o = (owner || "").toUpperCase();
  if (filter === "ALL") {
    return o !== "FREE";
  }
  return o === filter;
}
