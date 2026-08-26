import { describe, expect, it } from "vitest";

import { resolveHoldingMetrics } from "@/features/admin/portfolio/holdingsMetrics";
import { shouldShowHoldingByQuantity } from "@/features/admin/portfolio/holdingsRowPolicy";

describe("resolveHoldingMetrics", () => {
  it("AUTO + binding entry: valuation from qty×price, pnl from cost", () => {
    const m = resolveHoldingMetrics({
      quantity: "9.19117647",
      brokerAvgPrice: "0",
      autoEntryPrice: "1085",
      currentPrice: "1085",
      brokerEvalAmount: "0",
      brokerUnrealized: "0",
      brokerPurchaseAmount: "0",
      owner: "AUTO",
    });
    expect(m.avgPriceMissing).toBe(false);
    expect(m.avgPrice).toBe(1085);
    expect(m.valuationAmount).toBeCloseTo(9.19117647 * 1085, 2);
    expect(m.unrealizedPnl).not.toBeNull();
    expect(m.avgPriceSource).toBe("STRATEGY_BINDING_ENTRY");
  });

  it("missing avg: valuation ok, unrealized null (not fake 0)", () => {
    const m = resolveHoldingMetrics({
      quantity: "35.97",
      brokerAvgPrice: "0",
      autoEntryPrice: null,
      currentPrice: "278",
      brokerEvalAmount: "0",
      brokerUnrealized: "0",
      brokerPurchaseAmount: "0",
      owner: "AUTO",
    });
    expect(m.avgPriceMissing).toBe(true);
    expect(m.valuationAmount).toBeCloseTo(35.97 * 278, 1);
    expect(m.unrealizedPnl).toBeNull();
    expect(m.dataQuality).toBe("AVG_PRICE_MISSING");
  });
});

describe("zero quantity filter", () => {
  it("hides zero by default", () => {
    expect(shouldShowHoldingByQuantity("0", false)).toBe(false);
    expect(shouldShowHoldingByQuantity("9.1", false)).toBe(true);
    expect(shouldShowHoldingByQuantity("0", true)).toBe(true);
  });
});
