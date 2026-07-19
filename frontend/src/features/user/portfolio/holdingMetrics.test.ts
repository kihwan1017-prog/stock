import { describe, expect, it } from "vitest";

import {
  computeHoldingWeights,
  computeReturnRate,
} from "./holdingMetrics";

describe("STEP43 holdingMetrics", () => {
  it("평가금액 비중을 합계 100%로 나눈다", () => {
    expect(computeHoldingWeights([50_000, 50_000])).toEqual([50, 50]);
    expect(computeHoldingWeights([30_000, 70_000])[0]).toBeCloseTo(30);
    expect(computeHoldingWeights([30_000, 70_000])[1]).toBeCloseTo(70);
  });

  it("총평가가 0이면 비중 0", () => {
    expect(computeHoldingWeights([0, 0])).toEqual([0, 0]);
  });

  it("종목 수익률을 계산한다", () => {
    expect(computeReturnRate(110, 100)).toBeCloseTo(10);
    expect(computeReturnRate(90, 100)).toBeCloseTo(-10);
    expect(computeReturnRate(100, 0)).toBe(0);
  });
});
