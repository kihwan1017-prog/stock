import { describe, expect, it } from "vitest";
import { buildOpsStatusSummary } from "./opsStatusSummary";

describe("buildOpsStatusSummary", () => {
  it("uses server auto_trading_state as SoT", () => {
    const vm = buildOpsStatusSummary({
      auto_trading_state: "RUNNING",
      arm: "ON",
      arm_remaining_label: "2h 31m",
      activation_remaining_label: "5h 20m",
      runtime_stack: { label: "4/4 RUNNING" },
      unattended: {
        unattended_enabled: true,
        remaining_seconds: 66120,
      },
      market_feed: { status: "REAL_FRESH" },
      ai_state: "HOLD",
      primary_blocker: null,
    });
    expect(vm.autoTradingState).toBe("RUNNING");
    expect(vm.stackLabel).toBe("4/4 RUNNING");
    expect(vm.armLabel).toContain("2h 31m");
    expect(vm.unattendedLabel).toContain("24H ON");
    expect(vm.aiLabel).toBe("AI HOLD");
    expect(vm.color).toBe("success");
  });

  it("shows BLOCKED with primary blocker", () => {
    const vm = buildOpsStatusSummary({
      auto_trading_state: "BLOCKED",
      arm: "OFF",
      primary_blocker: "KILL_SWITCH_ACTIVE",
      runtime_stack: { label: "0/4 RUNNING" },
      unattended: { unattended_enabled: false },
      market_feed: { status: "REAL_STALE" },
      ai_state: "HOLD",
    });
    expect(vm.autoTradingState).toBe("BLOCKED");
    expect(vm.primaryBlocker).toBe("KILL_SWITCH_ACTIVE");
    expect(vm.color).toBe("error");
  });
});
