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
    // UBA 계좌 잠금 해제는 라이브 제어 패널이 사용한다. 분산락 force-unlock은 금지.
    expect(names).toContain("unlockRecoveryAccount");
    expect(
      names.some((n) => /forceUnlock|force.*UnlockLock|unlockRecoveryLock/i.test(n)),
    ).toBe(false);
  });
});
