import { describe, expect, it, vi } from "vitest";

import {
  CONFIRM_START_EXIT_MONITOR,
  CONFIRM_START_RUNTIME,
  CONFIRM_START_WORKER,
} from "./upbit24x7Confirmations";
import {
  runUpbit24x7StackStart,
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
    blockers: [],
    primary_blocker: null,
    ...overrides,
  };
}

describe("snapshotFromOpsStatus", () => {
  it("maps canonical ops fields", () => {
    const snap = snapshotFromOpsStatus(readyOps({ live: "ON", runtime: "RUNNING" }));
    expect(snap.live).toBe("ON");
    expect(snap.runtime).toBe("RUNNING");
    expect(snap.outboxWorker).toBe("STOPPED");
  });
});

describe("runUpbit24x7StackStart", () => {
  it("FAIL CLOSED when LIVE OFF — does not call start APIs", async () => {
    const startWorker = vi.fn();
    const startExitMonitor = vi.fn();
    const startRuntime = vi.fn();
    const outcome = await runUpbit24x7StackStart({
      fetchOpsStatus: async () => readyOps({ live: "OFF", blockers: ["LIVE_OFF"] }),
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
