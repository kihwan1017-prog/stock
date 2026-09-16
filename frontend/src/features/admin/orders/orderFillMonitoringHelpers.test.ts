import { describe, expect, it } from "vitest";

import {
  buildHourlyFillFlow,
  filterOrdersForMonitor,
  kstTodayStartIso,
  matchesMarket,
  summarizeDayOrders,
} from "./orderFillMonitoringHelpers";

describe("orderFillMonitoringHelpers", () => {
  it("kstTodayStartIso is KST midnight", () => {
    const iso = kstTodayStartIso();
    expect(iso).toMatch(/T00:00:00\+09:00$/);
  });

  it("matchesMarket maps KRX to KIWOOM", () => {
    expect(matchesMarket({ broker_code: "KRX" }, "KIWOOM")).toBe(true);
    expect(matchesMarket({ exchange_code: "UPBIT" }, "UPBIT")).toBe(true);
    expect(matchesMarket({ broker_code: "UPBIT" }, "KIWOOM")).toBe(false);
  });

  it("filterOrdersForMonitor keeps today AUTO fills", () => {
    const todayStart = new Date(kstTodayStartIso());
    const rows = [
      {
        order_id: 1,
        broker_code: "UPBIT",
        symbol: "KRW-BTC",
        side_code: "BUY",
        status_code: "FILLED",
        filled_quantity: 1,
        created_at: new Date().toISOString(),
        strategy_id: 10,
      },
      {
        order_id: 2,
        broker_code: "UPBIT",
        symbol: "KRW-ETH",
        side_code: "SELL",
        status_code: "FILLED",
        filled_quantity: 1,
        created_at: "2020-01-01T00:00:00Z",
        strategy_id: 10,
      },
    ];
    const filtered = filterOrdersForMonitor(rows, {
      market: "UPBIT",
      ownership: "ALL",
      todayOnly: true,
      todayStart,
    });
    expect(filtered.map((r) => r.order_id)).toEqual([1]);
  });

  it("summarizeDayOrders counts buy/sell/filled", () => {
    const s = summarizeDayOrders([
      { side_code: "BUY", status_code: "FILLED", filled_quantity: 1 },
      { side_code: "SELL", status_code: "FILLED", filled_quantity: 1 },
      { side_code: "BUY", status_code: "SUBMITTED", filled_quantity: 0 },
      { side_code: "BUY", status_code: "CANCELLED", filled_quantity: 0 },
    ]);
    expect(s.buyCount).toBe(3);
    expect(s.sellCount).toBe(1);
    expect(s.filledCount).toBe(2);
    expect(s.openCount).toBe(1);
    expect(s.cancelledCount).toBe(1);
  });

  it("buildHourlyFillFlow buckets filled orders by KST hour", () => {
    // 2026-08-27 01:30 KST = 2026-08-26 16:30 UTC
    const rows = [
      {
        side_code: "BUY",
        status_code: "FILLED",
        filled_quantity: 1,
        filled_at: "2026-08-26T16:30:00Z",
      },
      {
        side_code: "SELL",
        status_code: "FILLED",
        filled_quantity: 1,
        filled_at: "2026-08-26T16:45:00Z",
      },
    ];
    const flow = buildHourlyFillFlow(rows);
    const h01 = flow.find((p) => p.hour === "01");
    expect(h01?.buy).toBe(1);
    expect(h01?.sell).toBe(1);
  });
});
