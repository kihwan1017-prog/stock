import { describe, expect, it } from "vitest";

describe("BrokerSnapshotsPanel API surface", () => {
  it("STEP 8-5-18 orphan admin API가 존재한다", async () => {
    const api = await import("@/features/admin/api/adminApi");
    expect(api.listAdminBrokerSnapshots).toBeTypeOf("function");
    expect(api.getAdminBrokerSnapshotHealth).toBeTypeOf("function");
    expect(api.verifyAdminBrokerSnapshot).toBeTypeOf("function");
    expect(api.refreshAdminUbaSnapshot).toBeTypeOf("function");
    expect(api.releaseAdminUbaStaleSnapshot).toBeTypeOf("function");
    expect(api.listAdminOrphanBrokerSnapshots).toBeTypeOf("function");
    expect(api.rebindAdminOrphanBrokerSnapshot).toBeTypeOf("function");
    expect(api.retireAdminOrphanBrokerSnapshot).toBeTypeOf("function");
    expect(api.syncKiwoomAccount).toBeTypeOf("function");
    expect(api.syncUpbitAccount).toBeTypeOf("function");
  });

  it("Snapshot 상태 색상 매핑 (ORPHAN lifecycle)", async () => {
    const mod = await import(
      "@/features/admin/settlement/snapshotStatusColors"
    );
    for (const s of [
      "ACTIVE",
      "ORPHAN",
      "STALE",
      "SUPERSEDED",
      "INVALID",
      "REBIND_PENDING",
      "REBOUND",
      "RETIRED",
      "PURGED",
    ]) {
      expect(mod.SNAPSHOT_STATUS_COLOR[s]).toBeTruthy();
    }
  });
});
