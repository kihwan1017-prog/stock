/** 보유자산 행 필터 — zero CLOSED snapshot 제외 (테스트 가능) */

import { isEffectivelyZero } from "@/shared/utils/numericFormatKo";

/** ownership 맵에 없고 수량 0인 스냅샷 행은 제외 (stale CLOSED history) */
export function shouldIncludeHoldingPositionRow(
  positionQty: unknown,
  hasOwnershipEntry: boolean,
): boolean {
  if (hasOwnershipEntry) return true;
  return !isEffectivelyZero(positionQty);
}

/** ownership 미등록 + qty 0 → UNKNOWN 오판 방지용 기본 owner */
export function resolveHoldingOwner(
  ownershipOwner: string | null | undefined,
  hasOwnershipEntry: boolean,
  positionQty: unknown,
): string {
  if (hasOwnershipEntry) {
    return String(ownershipOwner ?? "UNKNOWN").toUpperCase();
  }
  if (isEffectivelyZero(positionQty)) {
    return "FREE";
  }
  return "UNKNOWN";
}
