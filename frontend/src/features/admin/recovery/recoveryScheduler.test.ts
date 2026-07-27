import { describe, expect, it } from "vitest";

describe("recovery scheduler frontend contract", () => {
  it("exposes admin scheduler APIs without secret accessors", async () => {
    const mod = await import("@/features/admin/api/adminApi");
    const names = Object.keys(mod);
    expect(names).toContain("listRecoverySchedulerJobs");
    expect(names).toContain("runRecoverySchedulerJobNow");
    expect(names).toContain("enableRecoverySchedulerJob");
    expect(names).toContain("disableRecoverySchedulerJob");
    expect(names).toContain("updateRecoverySchedulerJob");
    expect(names).toContain("listRecoverySchedulerRuns");
    expect(names.some((n) => /decrypt|exportSecret|getSecret/i.test(n))).toBe(
      false,
    );
  });
});
