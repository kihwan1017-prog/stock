import { describe, expect, it } from "vitest";

describe("upbit ambiguous resolver frontend contract", () => {
  it("exposes admin resolver APIs without claim/lock token accessors", async () => {
    const mod = await import("@/features/admin/api/adminApi");
    const names = Object.keys(mod);

    expect(names).toContain("getUpbitAmbiguousResolverStatus");
    expect(names).toContain("listUpbitAmbiguousResolverRuns");
    expect(names).toContain("getUpbitAmbiguousResolverRun");
    expect(names).toContain("runUpbitAmbiguousResolverNow");
    expect(names).toContain("retryUpbitAmbiguousLookup");
    expect(names).toContain("releaseUpbitAmbiguousStaleClaim");

    // STEP 8-5-14 — Resolver는 원격 조회 전용, 자동 제출 API는 노출하지 않는다
    expect(
      names.some((n) => /autoSubmit|submitAmbiguous|createOrder/i.test(n)),
    ).toBe(false);
    // Claim/Lock 토큰을 직접 노출하는 헬퍼는 없어야 한다
    expect(
      names.some((n) => /claimToken|lockToken|fencingToken/i.test(n)),
    ).toBe(false);
  });
});
