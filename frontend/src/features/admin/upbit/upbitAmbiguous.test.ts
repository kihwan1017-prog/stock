import { describe, expect, it } from "vitest";

describe("Upbit Ambiguous Orders API surface", () => {
  it("admin ambiguous APIs exist", async () => {
    const api = await import("@/features/admin/api/adminApi");
    expect(api.listUpbitAmbiguousOrders).toBeTypeOf("function");
    expect(api.lookupUpbitAmbiguousOrder).toBeTypeOf("function");
    expect(api.approveUpbitAmbiguousResubmit).toBeTypeOf("function");
    expect(api.rejectUpbitAmbiguousResubmit).toBeTypeOf("function");
  });
});
