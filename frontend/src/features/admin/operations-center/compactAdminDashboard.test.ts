import { describe, expect, it } from "vitest";

import {
  buildDashboardSearchParams,
  parseDashboardUrlState,
} from "./dashboardTabState";

describe("dashboardTabState", () => {
  it("defaults to summary tab", () => {
    const s = parseDashboardUrlState(new URLSearchParams());
    expect(s.tab).toBe("summary");
    expect(s.period).toBe("30D");
    expect(s.broker).toBe("ALL");
    expect(s.chart).toBe("cumulative_pnl");
  });

  it("parses performance filters from URL", () => {
    const s = parseDashboardUrlState(
      new URLSearchParams(
        "tab=performance&broker=UPBIT&period=7D&chart=cumulative_return",
      ),
    );
    expect(s.tab).toBe("performance");
    expect(s.broker).toBe("UPBIT");
    expect(s.period).toBe("7D");
    expect(s.chart).toBe("cumulative_return");
  });

  it("keeps broker in URL for all tabs", () => {
    const s = parseDashboardUrlState(
      new URLSearchParams("tab=summary&broker=KIWOOM&summaryPeriod=7D"),
    );
    expect(s.broker).toBe("KIWOOM");
    expect(s.summaryPeriod).toBe("7D");
  });

  it("builds search params for performance tab", () => {
    const current = parseDashboardUrlState(new URLSearchParams());
    const p = buildDashboardSearchParams(
      { tab: "performance", broker: "KIWOOM", period: "ALL", chart: "symbol_pnl" },
      current,
    );
    expect(p.get("tab")).toBe("performance");
    expect(p.get("broker")).toBe("KIWOOM");
    expect(p.get("chart")).toBe("symbol_pnl");
  });
});
