import { describe, expect, it } from "vitest";

import { asRecord, cell, extractRows } from "@/shared/utils/dataHelpers";
import {
  percentToRate,
  rateToPercent,
} from "@/shared/utils/riskRatePercent";
import {
  STRATEGY_DRAFT_STATUS_COLOR,
  STRATEGY_REQUEST_STATUS_COLOR,
} from "@/shared/utils/strategyStatusColors";

describe("shared/utils dataHelpers", () => {
  it("asRecord: object only", () => {
    expect(asRecord({ a: 1 })).toEqual({ a: 1 });
    expect(asRecord(null)).toBeNull();
    expect(asRecord([1])).toBeNull();
  });

  it("extractRows: array / nested keys", () => {
    expect(extractRows([{ id: 1 }])).toEqual([{ id: 1 }]);
    expect(extractRows({ items: [{ id: 2 }] })).toEqual([{ id: 2 }]);
    expect(extractRows({ orders: [{ id: 3 }] })).toEqual([{ id: 3 }]);
    expect(extractRows({})).toEqual([]);
  });

  it("cell: nullish / object / scalar", () => {
    expect(cell(null)).toBe("-");
    expect(cell(undefined)).toBe("-");
    expect(cell(12)).toBe("12");
    expect(cell({ x: 1 })).toBe('{"x":1}');
    expect(cell("0E-8")).toBe("0");
  });
});

describe("shared/utils strategyStatusColors", () => {
  it("request map covers review lifecycle", () => {
    expect(STRATEGY_REQUEST_STATUS_COLOR.PENDING_REVIEW).toBe("processing");
    expect(STRATEGY_REQUEST_STATUS_COLOR.APPROVED).toBe("success");
    expect(STRATEGY_REQUEST_STATUS_COLOR.REJECTED).toBe("error");
    expect(STRATEGY_REQUEST_STATUS_COLOR.CANCELLED).toBe("default");
    expect(STRATEGY_REQUEST_STATUS_COLOR.EXPIRED).toBe("warning");
  });

  it("draft map covers draft lifecycle", () => {
    expect(STRATEGY_DRAFT_STATUS_COLOR.DRAFT).toBe("processing");
    expect(STRATEGY_DRAFT_STATUS_COLOR.REGENERATED).toBe("default");
    expect(STRATEGY_DRAFT_STATUS_COLOR.SUPERSEDED).toBe("warning");
    expect(STRATEGY_DRAFT_STATUS_COLOR.ARCHIVED).toBe("error");
  });
});

describe("shared/utils riskRatePercent", () => {
  it("rateToPercent / percentToRate round-trip", () => {
    expect(rateToPercent(0.05)).toBe(5);
    expect(rateToPercent("0.123456")).toBe(12.3456);
    expect(rateToPercent(null)).toBeUndefined();
    expect(rateToPercent("x")).toBeUndefined();
    expect(percentToRate(5)).toBe(0.05);
    expect(percentToRate(null)).toBeNull();
  });
});
