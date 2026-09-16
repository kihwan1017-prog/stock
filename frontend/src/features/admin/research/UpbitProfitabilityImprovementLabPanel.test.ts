import { describe, expect, it } from "vitest";

import { formatNumResearch } from "@/features/admin/upbit/researchDetailFormat";

/** MA_DC churn 버킷 헬퍼 — UI 집계 계약 */
export function pickMaDcBucketN(churn: Record<string, unknown>, key: string): number {
  const bucket = churn[key];
  if (bucket == null || typeof bucket !== "object") return 0;
  const n = (bucket as Record<string, unknown>).N;
  return Number(n ?? 0);
}

describe("UpbitProfitabilityImprovementLabPanel helpers", () => {
  it("null-safe numeric format", () => {
    expect(formatNumResearch(null)).toBeTruthy();
    expect(formatNumResearch(undefined as unknown as null)).toBeTruthy();
  });

  it("MA_DC churn bucket N extraction", () => {
    const churn = {
      MA_DC_EXIT_COUNT: 7,
      MA_DC_REENTRY_LT_60S: { N: 2 },
      MA_DC_REENTRY_LT_180S: { N: 4 },
      MA_DC_REENTRY_LT_300S: { N: 5 },
    };
    expect(pickMaDcBucketN(churn, "MA_DC_REENTRY_LT_60S")).toBe(2);
    expect(pickMaDcBucketN(churn, "MA_DC_REENTRY_LT_300S")).toBe(5);
    expect(pickMaDcBucketN(churn, "MISSING")).toBe(0);
  });
});
