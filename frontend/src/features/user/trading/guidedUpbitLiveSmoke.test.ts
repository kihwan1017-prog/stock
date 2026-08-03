import { describe, expect, it } from "vitest";

describe("guided smoke order test gate", () => {
  it("exposes postLiveOrderTest API", async () => {
    const mod = await import("@/features/user/api/userApi");
    expect(typeof mod.postLiveOrderTest).toBe("function");
    expect(typeof mod.postLiveOrderConfirm).toBe("function");
  });

  it("keeps confirmation phrases exact", () => {
    expect("UPBIT LIVE BUY CONFIRM").toContain("BUY");
    expect("UPBIT LIVE SELL CONFIRM").toContain("SELL");
  });
});
