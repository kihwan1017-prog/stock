import { describe, expect, it } from "vitest";

describe("AccountSettlementsPanel API surface", () => {
  it("STEP 8-5-16 admin settlements API가 모두 존재한다", async () => {
    const api = await import("@/features/admin/api/adminApi");
    expect(api.listAdminSettlements).toBeTypeOf("function");
    expect(api.getAdminSettlementHealth).toBeTypeOf("function");
    expect(api.getAdminSettlement).toBeTypeOf("function");
    expect(api.listAdminSettlementIssues).toBeTypeOf("function");
    expect(api.retryAdminSettlement).toBeTypeOf("function");
    expect(api.reconcileAdminSettlement).toBeTypeOf("function");
    expect(api.resolveAdminSettlementIssue).toBeTypeOf("function");
    expect(api.runAdminUbaSettlement).toBeTypeOf("function");
    expect(api.runAdminPaperSettlement).toBeTypeOf("function");
  });

  it("모든 Settlement 상태에 색상이 매핑되어 있다", async () => {
    const mod = await import(
      "@/features/admin/settlement/settlementStatusColors"
    );
    const required = [
      "PENDING",
      "RUNNING",
      "SUCCEEDED",
      "SUCCEEDED_WITH_WARNINGS",
      "RETRY_PENDING",
      "FAILED",
      "MANUAL_REVIEW_REQUIRED",
      "SKIPPED",
      "SUPERSEDED",
    ];
    for (const status of required) {
      expect(mod.SETTLEMENT_STATUS_COLOR[status]).toBeTruthy();
    }
  });
});
