import { describe, expect, it } from "vitest";

/** Lock 상태 표시 규칙 (UI 단위) */
function lockLabel(status: string, stale: boolean): string {
  return stale ? `${status}·STALE` : status;
}

describe("RecoveryDistributedLockPanel helpers", () => {
  it("stale 상태를 라벨에 표시한다", () => {
    expect(lockLabel("HELD", true)).toBe("HELD·STALE");
    expect(lockLabel("HELD", false)).toBe("HELD");
  });

  it("강제 해제 API 경로를 노출하지 않는다", async () => {
    const api = await import("@/features/admin/api/adminApi");
    const names = Object.keys(api);
    expect(names).toContain("listAdminRecoveryLocks");
    expect(names).toContain("getAdminRecoveryLock");
    expect(names.some((n) => /force.*unlock|unlockRecovery/i.test(n))).toBe(
      false,
    );
  });
});
