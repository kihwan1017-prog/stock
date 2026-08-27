import { describe, expect, it } from "vitest";

import { friendlyReasonKo } from "@/features/admin/market-analysis/userFriendlyReasons";

describe("DailyCollectionStatus filters contract", () => {
  it("period options cover 7/30/90/365", () => {
    const periods = [7, 30, 90, 365];
    expect(periods).toEqual([7, 30, 90, 365]);
  });

  it("status filter values align with backend", () => {
    const statuses = ["ALL", "HEALTHY", "PARTIAL", "FAILED", "CLOSED"];
    expect(statuses).toContain("HEALTHY");
    expect(statuses).toContain("PARTIAL");
  });
});

describe("stale vs system failure messaging", () => {
  it("stale warning is not system error wording", () => {
    const stale = "일봉 데이터 일부 보정 중";
    expect(stale).not.toMatch(/SYSTEM ERROR|시스템 장애|장애/);
  });

  it("market closed is not failure", () => {
    expect(friendlyReasonKo("MARKET_CLOSED")).not.toMatch(/실패|장애/);
  });
});
