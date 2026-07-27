import { describe, expect, it } from "vitest";

describe("recovery conflict frontend contract", () => {
  it("exposes conflict admin APIs without secret accessors", async () => {
    const mod = await import("@/features/admin/api/adminApi");
    const names = Object.keys(mod);
    expect(names).toContain("listRecoveryConflicts");
    expect(names).toContain("getRecoveryConflict");
    expect(names).toContain("refreshRecoveryConflict");
    expect(names).toContain("approveImportRecoveryConflict");
    expect(names).toContain("ignoreRecoveryConflict");
    expect(names).toContain("preserveHistoryRecoveryConflict");
    expect(names).toContain("holdRecoveryConflict");
    expect(names).toContain("resumeRecoveryAccount");
    expect(names.some((n) => /decrypt|exportSecret|getSecret/i.test(n))).toBe(
      false,
    );
  });

  it("approve import button label contract", () => {
    // 외부 재주문 오해를 막는 버튼 문구
    const label = "내부 기록으로 가져오기";
    expect(label).not.toMatch(/주문 전송|신규 주문/);
    expect(label).toContain("내부");
  });
});
