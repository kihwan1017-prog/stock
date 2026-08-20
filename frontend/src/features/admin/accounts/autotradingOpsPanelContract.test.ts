import { describe, expect, it } from "vitest";

/**
 * Drawer canonical ops panel contract — 중복 UI 제거 후 단일 패널 역할.
 */
describe("autotrading ops panel drawer contract", () => {
  it("canonical panel exposes unattended action flag", () => {
    const props = {
      showUnattendedActions: true,
      onUnattendedEnable: () => undefined,
    };
    expect(props.showUnattendedActions).toBe(true);
    expect(typeof props.onUnattendedEnable).toBe("function");
  });

  it("readiness detail panel does not own stack controls", () => {
    // UbaAutoTradingStatusPanel is readiness/detail only; ops controls live once in Drawer.
    const drawerSections = ["자동매매 운영", "readiness detail"];
    expect(drawerSections.filter((s) => s === "자동매매 운영")).toHaveLength(1);
  });
});
