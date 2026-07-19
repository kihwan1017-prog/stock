import { describe, expect, it } from "vitest";

import { filterOpenOrders, isOpenOrderStatus } from "./openOrders";

describe("STEP44 openOrders", () => {
  it("OPEN류 상태를 미체결로 본다", () => {
    expect(isOpenOrderStatus("NEW")).toBe(true);
    expect(isOpenOrderStatus("PARTIAL")).toBe(true);
    expect(isOpenOrderStatus("FILLED")).toBe(false);
    expect(isOpenOrderStatus("CANCELLED")).toBe(false);
  });

  it("미체결만 필터한다", () => {
    const rows = [
      { order_id: 1, status_code: "NEW" },
      { order_id: 2, status_code: "FILLED" },
      { order_id: 3, status_code: "WORKING" },
    ];
    expect(filterOpenOrders(rows).map((r) => r.order_id)).toEqual([1, 3]);
  });
});
