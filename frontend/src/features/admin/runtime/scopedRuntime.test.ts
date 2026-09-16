import { describe, expect, it } from "vitest";

describe("scoped runtime frontend contract", () => {
  it("exposes admin runtime APIs without global getters", async () => {
    const mod = await import("@/features/admin/api/adminApi");
    const names = Object.keys(mod);
    expect(names).toContain("listAdminRuntimes");
    expect(names).toContain("pauseAdminRuntime");
    expect(names).toContain("resumeAdminRuntime");
    expect(names).toContain("reloadAdminRuntime");
    expect(names).toContain("stopAdminRuntime");
    expect(names).not.toContain("getDefaultRuntime");
    expect(names).not.toContain("getGlobalRuntime");
  });

  it("exposes user runtime list API", async () => {
    const mod = await import("@/features/user/api/userApi");
    expect(Object.keys(mod)).toContain("listMyRuntimes");
    expect(Object.keys(mod)).toContain("listAccountRuntimes");
  });
});
