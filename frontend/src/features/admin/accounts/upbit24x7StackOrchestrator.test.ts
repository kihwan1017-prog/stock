import { describe, expect, it, vi } from "vitest";

import {
  CONFIRM_START_EXIT_MONITOR,
  CONFIRM_START_RUNTIME,
  CONFIRM_START_WORKER,
  CONFIRM_STOP_EXIT_MONITOR,
  CONFIRM_STOP_RUNTIME,
  CONFIRM_STOP_WORKER,
} from "./upbit24x7Confirmations";
import {
  runUpbit24x7StackStart,
  runUpbit24x7StackStop,
  snapshotFromOpsStatus,
} from "./upbit24x7StackOrchestrator";

function readyOps(overrides: Record<string, unknown> = {}) {
  return {
    auto_trading_state: "WAITING_SIGNAL",
    live: "ON",
    arm: "ON",
    activation: "ACTIVE",
    runtime: "STOPPED",
    runner: "STOPPED",
    outbox_worker: "STOPPED",
    exit_monitor: "STOPPED",
    runtime_stack: {
      label: "0/4 RUNNING",
      runtime: "STOPPED",
      runner: "STOPPED",
      outbox_worker: "STOPPED",
      exit_monitor: "STOPPED",
    },
    unattended: { unattended_enabled: false },
    blockers: [],
    primary_blocker: null,
    ...overrides,
  };
}

describe("snapshotFromOpsStatus", () => {
  it("maps canonical ops fields", () => {
    const snap = snapshotFromOpsStatus(
      readyOps({
        live: "ON",
        runtime: "RUNNING",
        unattended: { unattended_enabled: true },
      }),
    );
    expect(snap.live).toBe("ON");
    expect(snap.runtime).toBe("RUNNING");
    expect(snap.unattendedEnabled).toBe(false);
    expect(snap.needsReauthorize).toBe(true);
    expect(snap.outboxWorker).toBe("STOPPED");
  });

  it("maps remaining and AI fields", () => {
    const snap = snapshotFromOpsStatus(
      readyOps({
        live: "ON",
        arm: "ON",
        arm_remaining_label: "2h 10m",
        activation: "ACTIVE",
        activation_remaining_label: "5h 00m",
        ai_state: "ALLOW",
        unattended: {
          unattended_enabled: true,
          status_code: "ACTIVE",
          entry_authorized: true,
          remaining_seconds: 7200,
          needs_reauthorize: false,
        },
        runtime_stack: { label: "4/4 RUNNING" },
        primary_blocker: null,
      }),
    );
    expect(snap.unattendedEnabled).toBe(true);
    expect(snap.needsReauthorize).toBe(false);
    expect(snap.unattendedRemainingLabel).toContain("h");
    expect(snap.armRemainingLabel).toBe("2h 10m");
    expect(snap.activationRemainingLabel).toBe("5h 00m");
    expect(snap.aiState).toBe("ALLOW");
    expect(snap.primaryBlocker).toBeNull();
    expect(snap.stackLabel).toBe("4/4 RUNNING");
  });
});

describe("runUpbit24x7StackStart", () => {
  it("FAIL CLOSED when LIVE OFF — does not call start APIs", async () => {
    const startWorker = vi.fn();
    const startExitMonitor = vi.fn();
    const startRuntime = vi.fn();
    const outcome = await runUpbit24x7StackStart({
      fetchOpsStatus: async () =>
        readyOps({ live: "OFF", blockers: ["LIVE_OFF"] }),
      startWorker,
      startExitMonitor,
      startRuntime,
    });
    expect(outcome.ok).toBe(false);
    expect(outcome.failedStep).toBe("GATE_LIVE");
    expect(startWorker).not.toHaveBeenCalled();
    expect(startRuntime).not.toHaveBeenCalled();
  });

  it("starts Worker → Exit → Runtime with canonical phrases", async () => {
    const startWorker = vi.fn(async () => ({ ok: true }));
    const startExitMonitor = vi.fn(async () => ({ ok: true }));
    const startRuntime = vi.fn(async () => ({ ok: true }));
    let calls = 0;
    const outcome = await runUpbit24x7StackStart({
      fetchOpsStatus: async () => {
        calls += 1;
        if (calls === 1) return readyOps();
        return readyOps({
          runtime: "RUNNING",
          runner: "RUNNING",
          outbox_worker: "RUNNING",
          exit_monitor: "RUNNING",
          auto_trading_state: "RUNNING",
          runtime_stack: { label: "4/4 RUNNING" },
        });
      },
      startWorker,
      startExitMonitor,
      startRuntime,
    });
    expect(outcome.ok).toBe(true);
    expect(startWorker).toHaveBeenCalledWith(CONFIRM_START_WORKER);
    expect(startExitMonitor).toHaveBeenCalledWith(CONFIRM_START_EXIT_MONITOR);
    expect(startRuntime).toHaveBeenCalledWith(CONFIRM_START_RUNTIME);
    expect(outcome.steps.every((s) => s.status === "PASS")).toBe(true);
  });

  it("skips already-running components and still PASSes", async () => {
    const startWorker = vi.fn();
    const startExitMonitor = vi.fn();
    const startRuntime = vi.fn();
    const outcome = await runUpbit24x7StackStart({
      fetchOpsStatus: async () =>
        readyOps({
          outbox_worker: "RUNNING",
          exit_monitor: "RUNNING",
          runtime: "RUNNING",
          runner: "RUNNING",
        }),
      startWorker,
      startExitMonitor,
      startRuntime,
    });
    expect(outcome.ok).toBe(true);
    expect(startWorker).not.toHaveBeenCalled();
    expect(startExitMonitor).not.toHaveBeenCalled();
    expect(startRuntime).not.toHaveBeenCalled();
  });

  it("FAIL CLOSED on worker error and skips later steps", async () => {
    const outcome = await runUpbit24x7StackStart({
      fetchOpsStatus: async () => readyOps(),
      startWorker: async () => {
        throw new Error("WORKER_GATE");
      },
      startExitMonitor: async () => ({ ok: true }),
      startRuntime: async () => ({ ok: true }),
    });
    expect(outcome.ok).toBe(false);
    expect(outcome.failedStep).toBe("WORKER_START");
    expect(outcome.steps.find((s) => s.id === "RUNTIME_START")?.status).toBe(
      "SKIPPED",
    );
  });
});

describe("runUpbit24x7StackStop", () => {
  it("stops Runtime → Exit → Worker with canonical phrases", async () => {
    const stopRuntime = vi.fn(async () => ({ ok: true }));
    const stopExitMonitor = vi.fn(async () => ({ ok: true }));
    const stopWorker = vi.fn(async () => ({ ok: true }));
    const outcome = await runUpbit24x7StackStop({
      fetchOpsStatus: async () =>
        readyOps({
          runtime: "RUNNING",
          exit_monitor: "RUNNING",
          outbox_worker: "RUNNING",
          runtime_stack: { label: "4/4 RUNNING" },
        }),
      stopRuntime,
      stopExitMonitor,
      stopWorker,
    });
    expect(outcome.ok).toBe(true);
    expect(stopRuntime).toHaveBeenCalledWith(CONFIRM_STOP_RUNTIME);
    expect(stopExitMonitor).toHaveBeenCalledWith(CONFIRM_STOP_EXIT_MONITOR);
    expect(stopWorker).toHaveBeenCalledWith(CONFIRM_STOP_WORKER);
  });

  it("FAIL CLOSED on runtime stop error", async () => {
    const stopExitMonitor = vi.fn();
    const outcome = await runUpbit24x7StackStop({
      fetchOpsStatus: async () =>
        readyOps({ runtime: "RUNNING", exit_monitor: "RUNNING" }),
      stopRuntime: async () => {
        throw new Error("RUNTIME_STOP_DENIED");
      },
      stopExitMonitor,
      stopWorker: async () => ({ ok: true }),
    });
    expect(outcome.ok).toBe(false);
    expect(outcome.failedStep).toBe("RUNTIME_STOP");
    expect(stopExitMonitor).not.toHaveBeenCalled();
  });
});
