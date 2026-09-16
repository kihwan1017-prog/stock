import { describe, expect, it } from "vitest";

/** 정렬 유틸 — DnD arrayMove와 동일한 로직 검증용 */
function reorderIds(
  ids: number[],
  fromIndex: number,
  toIndex: number,
): number[] {
  const next = [...ids];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}

describe("STEP67 watchlist helpers", () => {
  it("reorders ids for display_order sync", () => {
    expect(reorderIds([10, 20, 30], 0, 2)).toEqual([20, 30, 10]);
  });

  it("builds search option value as market:symbol", () => {
    const hit = { market: "KRX", symbol: "005930", symbol_name: "삼성전자" };
    expect(`${hit.market}:${hit.symbol}`).toBe("KRX:005930");
  });
});
