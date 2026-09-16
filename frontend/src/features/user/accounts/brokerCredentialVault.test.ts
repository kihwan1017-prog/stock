"use client";

import { describe, expect, it } from "vitest";

/**
 * STEP 8-5-2 — Frontend는 Secret 원문 조회 API를 노출하지 않는다.
 * (타입·경로 계약 검증)
 */
describe("broker credential vault frontend contract", () => {
  it("user credential endpoints do not include secret fetch path", async () => {
    const mod = await import("@/features/user/api/userApi");
    const names = Object.keys(mod);
    expect(names).toContain("getUserBrokerCredentialStatus");
    expect(names).toContain("registerUserBrokerCredential");
    expect(names).toContain("replaceUserBrokerCredential");
    expect(names).toContain("revokeUserBrokerCredential");
    expect(names).toContain("verifyUserBrokerCredential");
    expect(names.some((n) => /decrypt|exportSecret|getSecret/i.test(n))).toBe(
      false,
    );
  });

  it("admin credential endpoints exclude plaintext accessors", async () => {
    const mod = await import("@/features/admin/api/adminApi");
    const names = Object.keys(mod);
    expect(names).toContain("getAdminBrokerCredentialStatus");
    expect(names).toContain("verifyAdminBrokerCredential");
    expect(names).toContain("revokeAdminBrokerCredential");
    expect(names.some((n) => /decrypt|exportSecret|getSecret/i.test(n))).toBe(
      false,
    );
  });
});
