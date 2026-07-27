import { describe, expect, it } from "vitest";

describe("MarketCalendarPanel API surface", () => {
  it("admin calendar API가 존재하고 USER sync는 없다", async () => {
    const api = await import("@/features/admin/api/adminApi");
    expect(api.listAdminMarketCalendar).toBeTypeOf("function");
    expect(api.syncAdminMarketCalendar).toBeTypeOf("function");
    expect(api.getUserMarketCalendarStatus).toBeTypeOf("function");
    expect(api.listAdminCalendarChangeRequests).toBeTypeOf("function");
    expect(api.createAdminCalendarChangeRequest).toBeTypeOf("function");
    expect(api.applyAdminCalendarChangeRequest).toBeTypeOf("function");
    expect(api.rollbackAdminCalendarDay).toBeTypeOf("function");
    expect(
      Object.keys(api).some((n) => /user.*calendar.*sync/i.test(n)),
    ).toBe(false);
  });
});
