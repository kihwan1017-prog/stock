import { describe, expect, it } from "vitest";

describe("MarketSessionJobsPanel API surface", () => {
  it("STEP 8-5-15 admin market-session-jobs API가 모두 존재한다", async () => {
    const api = await import("@/features/admin/api/adminApi");
    expect(api.listAdminMarketSessionJobs).toBeTypeOf("function");
    expect(api.getAdminMarketSessionJobHealth).toBeTypeOf("function");
    expect(api.getAdminMarketSessionJob).toBeTypeOf("function");
    expect(api.getAdminMarketSessionJobRuns).toBeTypeOf("function");
    expect(api.reconcileAdminMarketSessionJobs).toBeTypeOf("function");
    expect(api.runNowAdminMarketSessionJob).toBeTypeOf("function");
    expect(api.retryAdminMarketSessionJob).toBeTypeOf("function");
    expect(api.cancelAdminMarketSessionJob).toBeTypeOf("function");
    expect(api.releaseStaleClaimAdminMarketSessionJob).toBeTypeOf("function");
  });
});

describe("JOB_STATUS_COLOR", () => {
  it("모든 Job 상태(MarketSessionJobStatus)에 색상이 매핑되어 있다", async () => {
    const { JOB_STATUS_COLOR } = await import(
      "@/features/admin/market/jobStatusColors"
    );
    const expectedStatuses = [
      "SCHEDULED",
      "CLAIMED",
      "RUNNING",
      "SUCCEEDED",
      "FAILED",
      "RETRY_PENDING",
      "SKIPPED",
      "SUPERSEDED",
      "CANCELLED",
      "EXPIRED",
    ];
    for (const status of expectedStatuses) {
      expect(JOB_STATUS_COLOR[status]).toBeTypeOf("string");
    }
  });
});
