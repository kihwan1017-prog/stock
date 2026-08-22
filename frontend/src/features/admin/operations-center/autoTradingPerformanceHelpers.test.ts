import { describe, expect, it } from "vitest";

import {
  formatKrw,
  formatPct,
  parsePerformanceSummary,
  pnlColor,
} from "./autoTradingPerformanceHelpers";

describe("parsePerformanceSummary", () => {
  it("parses API summary fields", () => {
    const s = parsePerformanceSummary({
      today_realized_pnl: "38.21",
      today_return_pct: "0.76",
      cumulative_realized_pnl: "38.21",
      cumulative_return_pct: "0.76",
      current_unrealized_pnl: "0",
      win_rate_pct: "100",
      closed_trade_count: 1,
      open_position_count: 0,
      avg_trade_return_pct: "0.76",
    });
    expect(s.todayRealizedPnl).toBe(38.21);
    expect(s.closedTradeCount).toBe(1);
    expect(s.winRatePct).toBe(100);
  });
});

describe("formatters", () => {
  it("formats KRW and percent", () => {
    expect(formatKrw(1234)).toContain("1,234");
    expect(formatPct(0.76)).toBe("+0.76%");
    expect(formatPct(-1.2)).toBe("-1.20%");
    expect(formatPct(null)).toBe("—");
  });

  it("pnl color", () => {
    expect(pnlColor(10)).toBe("#3f8600");
    expect(pnlColor(-1)).toBe("#cf1322");
    expect(pnlColor(0)).toBeUndefined();
  });
});
