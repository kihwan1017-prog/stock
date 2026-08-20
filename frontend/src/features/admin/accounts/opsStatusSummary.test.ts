import { describe, expect, it } from "vitest";
import { buildOpsStatusSummary } from "./opsStatusSummary";

describe("buildOpsStatusSummary", () => {
  it("uses server auto_trading_state as SoT", () => {
    const vm = buildOpsStatusSummary({
      auto_trading_state: "RUNNING",
      live: "ON",
      arm: "ON",
      arm_remaining_label: "2h 31m",
      activation_remaining_label: "5h 20m",
      runtime: "RUNNING",
      runner: "RUNNING",
      outbox_worker: "RUNNING",
      exit_monitor: "RUNNING",
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
    expect(vm.liveLabel).toBe("LIVE ON");
    expect(vm.stackLabel).toBe("4/4 RUNNING");
    expect(vm.armLabel).toContain("2h 31m");
    expect(vm.unattendedLabel).toContain("24H ON");
    expect(vm.runtimeLabel).toBe("RT RUNNING");
    expect(vm.workerLabel).toBe("WK RUNNING");
    expect(vm.exitLabel).toBe("EX RUNNING");
    expect(vm.aiLabel).toBe("AI HOLD");
    expect(vm.color).toBe("success");
  });

  it("shows BLOCKED with primary blocker", () => {
    const vm = buildOpsStatusSummary({
      auto_trading_state: "BLOCKED",
      live: "OFF",
      arm: "OFF",
      primary_blocker: "KILL_SWITCH_ACTIVE",
      runtime_stack: { label: "0/4 RUNNING" },
      unattended: { unattended_enabled: false },
      market_feed: { status: "REAL_STALE" },
      ai_state: "HOLD",
    });
    expect(vm.autoTradingState).toBe("BLOCKED");
    expect(vm.liveLabel).toBe("LIVE OFF");
    expect(vm.primaryBlocker).toBe("KILL_SWITCH_ACTIVE");
    expect(vm.color).toBe("error");
  });

  it("maps WAITING_SIGNAL color", () => {
    const vm = buildOpsStatusSummary({
      auto_trading_state: "WAITING_SIGNAL",
      live: "ON",
      arm: "ON",
      runtime_stack: { label: "1/4 RUNNING" },
      unattended: { unattended_enabled: false },
    });
    expect(vm.color).toBe("processing");
  });
});
