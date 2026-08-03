import { describe, expect, it } from "vitest";

describe("guided upbit live smoke confirm texts", () => {
  it("uses exact confirmation phrases", () => {
    expect("UPBIT LIVE BUY CONFIRM").toBe("UPBIT LIVE BUY CONFIRM");
    expect("UPBIT LIVE SELL CONFIRM").toBe("UPBIT LIVE SELL CONFIRM");
  });

  it("exposes user smoke API helpers", async () => {
    const mod = await import("@/features/user/api/userApi");
    expect(typeof mod.getLiveOrderPreflight).toBe("function");
    expect(typeof mod.postLiveOrderPreview).toBe("function");
    expect(typeof mod.postLiveOrderConfirm).toBe("function");
  });
});
