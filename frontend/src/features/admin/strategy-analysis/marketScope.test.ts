import { describe, expect, it } from "vitest";

import {
  isKiwoomVisible,
  isUpbitOnlyResearch,
  isUpbitVisible,
  parseStrategyMarket,
  withMarketQuery,
} from "@/features/admin/strategy-analysis/marketScope";

describe("marketScope", () => {
  it("parses market query aliases", () => {
    expect(parseStrategyMarket("UPBIT")).toBe("UPBIT");
    expect(parseStrategyMarket("kiwoom")).toBe("KIWOOM");
    expect(parseStrategyMarket("KRX")).toBe("KIWOOM");
    expect(parseStrategyMarket(null)).toBe("ALL");
    expect(parseStrategyMarket("")).toBe("ALL");
  });

  it("does not mix CLEAN into KIWOOM-only view", () => {
    expect(isUpbitOnlyResearch("UPBIT")).toBe(true);
    expect(isUpbitOnlyResearch("ALL")).toBe(true);
    expect(isUpbitOnlyResearch("KIWOOM")).toBe(false);
  });

  it("visibility flags isolate markets", () => {
    expect(isKiwoomVisible("KIWOOM")).toBe(true);
    expect(isUpbitVisible("KIWOOM")).toBe(false);
    expect(isKiwoomVisible("UPBIT")).toBe(false);
    expect(isUpbitVisible("UPBIT")).toBe(true);
    expect(isKiwoomVisible("ALL")).toBe(true);
    expect(isUpbitVisible("ALL")).toBe(true);
  });

  it("withMarketQuery preserves path and sets market", () => {
    expect(withMarketQuery("/admin/research", "UPBIT")).toBe(
      "/admin/research?market=UPBIT",
    );
    expect(withMarketQuery("/admin/research?x=1", "KIWOOM")).toBe(
      "/admin/research?x=1&market=KIWOOM",
    );
    expect(withMarketQuery("/admin/research", "ALL")).toBe("/admin/research");
  });
});
