/**
 * UPBIT 24H 운영 스택 fail-closed 오케스트레이터.
 * LIVE/ARM/Activation 은 강한 승인 경로에서만 켜고,
 * 여기서는 Worker → Exit Monitor → Runtime 만 canonical API로 기동한다.
 */

import {
  CONFIRM_START_EXIT_MONITOR,
  CONFIRM_START_RUNTIME,
  CONFIRM_START_WORKER,
} from "./upbit24x7Confirmations";

export type StackStartStepId =
  | "PREFLIGHT"
  | "GATE_ACTIVATION"
  | "GATE_LIVE"
  | "GATE_ARM"
  | "WORKER_START"
  | "EXIT_MONITOR_START"
  | "RUNTIME_START";

export type StackStartStepStatus = "PENDING" | "RUNNING" | "PASS" | "FAIL" | "SKIPPED";

export type StackStartStepResult = {
  id: StackStartStepId;
  status: StackStartStepStatus;
  reason?: string;
};

export type StackStartSnapshot = {
  live: string;
  arm: string;
  activation: string;
  runtime: string;
  runner: string;
  outboxWorker: string;
  exitMonitor: string;
  autoTradingState: string;
  blockers: string[];
  primaryBlocker: string | null;
};

export type StackStartOutcome = {
  ok: boolean;
  failedStep: StackStartStepId | null;
  failedReason: string | null;
  steps: StackStartStepResult[];
  snapshot: StackStartSnapshot | null;
};

export type StackStartDeps = {
  /** ops-status 조회 (canonical) */
  fetchOpsStatus: () => Promise<unknown>;
  startWorker: (confirmationText: string) => Promise<unknown>;
  startExitMonitor: (confirmationText: string) => Promise<unknown>;
  startRuntime: (confirmationText: string) => Promise<unknown>;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function snapshotFromOpsStatus(payload: unknown): StackStartSnapshot {
  const root = asRecord(payload);
  const stack = asRecord(root.runtime_stack);
  return {
    live: String(root.live ?? "OFF").toUpperCase(),
    arm: String(root.arm ?? "OFF").toUpperCase(),
    activation: String(root.activation ?? "INACTIVE").toUpperCase(),
    runtime: String(root.runtime ?? stack.runtime ?? "STOPPED").toUpperCase(),
    runner: String(root.runner ?? stack.runner ?? "STOPPED").toUpperCase(),
    outboxWorker: String(
      root.outbox_worker ?? stack.outbox_worker ?? "STOPPED",
    ).toUpperCase(),
    exitMonitor: String(
      root.exit_monitor ?? stack.exit_monitor ?? "STOPPED",
    ).toUpperCase(),
    autoTradingState: String(root.auto_trading_state ?? "STOPPED").toUpperCase(),
    blockers: Array.isArray(root.blockers)
      ? root.blockers.map((x) => String(x))
      : [],
    primaryBlocker:
      root.primary_blocker != null ? String(root.primary_blocker) : null,
  };
}

function errMessage(err: unknown): string {
  if (err && typeof err === "object") {
    const e = err as {
      message?: string;
      detail?: { message?: string; code?: string };
    };
    if (e.detail?.message) {
      return e.detail.code
        ? `${e.detail.code}: ${e.detail.message}`
        : e.detail.message;
    }
    if (e.message) return e.message;
  }
  return String(err ?? "UNKNOWN_ERROR");
}

const STEP_ORDER: StackStartStepId[] = [
  "PREFLIGHT",
  "GATE_ACTIVATION",
  "GATE_LIVE",
  "GATE_ARM",
  "WORKER_START",
  "EXIT_MONITOR_START",
  "RUNTIME_START",
];

/**
 * Preflight/gate 통과 후 Worker → Exit → Runtime 순 기동.
 * 어느 단계든 실패 시 즉시 중단(FAIL CLOSED). safety gate 우회 없음.
 */
export async function runUpbit24x7StackStart(
  deps: StackStartDeps,
): Promise<StackStartOutcome> {
  const steps: StackStartStepResult[] = STEP_ORDER.map((id) => ({
    id,
    status: "PENDING",
  }));

  const mark = (
    id: StackStartStepId,
    status: StackStartStepStatus,
    reason?: string,
  ) => {
    const row = steps.find((s) => s.id === id);
    if (row) {
      row.status = status;
      row.reason = reason;
    }
  };

  let snapshot: StackStartSnapshot | null = null;

  const fail = (
    id: StackStartStepId,
    reason: string,
  ): StackStartOutcome => {
    mark(id, "FAIL", reason);
    // 이후 단계는 SKIPPED
    let seen = false;
    for (const s of steps) {
      if (s.id === id) {
        seen = true;
        continue;
      }
      if (seen && s.status === "PENDING") {
        s.status = "SKIPPED";
      }
    }
    return {
      ok: false,
      failedStep: id,
      failedReason: reason,
      steps,
      snapshot,
    };
  };

  // 1) Preflight = ops-status 조회
  mark("PREFLIGHT", "RUNNING");
  try {
    const raw = await deps.fetchOpsStatus();
    snapshot = snapshotFromOpsStatus(raw);
    mark("PREFLIGHT", "PASS");
  } catch (err) {
    return fail("PREFLIGHT", errMessage(err));
  }

  if (!snapshot) {
    return fail("PREFLIGHT", "ops-status snapshot missing");
  }

  const snap = snapshot;

  // 2–4) Gates — LIVE/ARM/Activation 은 여기서 켜지 않음
  mark("GATE_ACTIVATION", "RUNNING");
  if (snap.activation !== "ACTIVE") {
    return fail(
      "GATE_ACTIVATION",
      `Activation이 ACTIVE가 아닙니다 (현재: ${snap.activation}). LIVE 패널에서 Activation 후 재시도하세요.`,
    );
  }
  mark("GATE_ACTIVATION", "PASS");

  mark("GATE_LIVE", "RUNNING");
  if (snap.live !== "ON") {
    return fail(
      "GATE_LIVE",
      "LIVE OFF — LIVE ON은 강한 승인(approval phrase)이 필요합니다. LIVE 패널에서 켠 뒤 재시도하세요.",
    );
  }
  mark("GATE_LIVE", "PASS");

  mark("GATE_ARM", "RUNNING");
  if (snap.arm !== "ON") {
    return fail(
      "GATE_ARM",
      "ARM OFF — ARM ON은 LIVE 패널에서 승인 후 수행하세요.",
    );
  }
  mark("GATE_ARM", "PASS");

  // 5) Worker
  mark("WORKER_START", "RUNNING");
  if (snap.outboxWorker === "RUNNING") {
    mark("WORKER_START", "PASS", "already RUNNING");
  } else {
    try {
      await deps.startWorker(CONFIRM_START_WORKER);
      mark("WORKER_START", "PASS");
    } catch (err) {
      return fail("WORKER_START", errMessage(err));
    }
  }

  // 6) Exit Monitor
  mark("EXIT_MONITOR_START", "RUNNING");
  if (snap.exitMonitor === "RUNNING") {
    mark("EXIT_MONITOR_START", "PASS", "already RUNNING");
  } else {
    try {
      await deps.startExitMonitor(CONFIRM_START_EXIT_MONITOR);
      mark("EXIT_MONITOR_START", "PASS");
    } catch (err) {
      return fail("EXIT_MONITOR_START", errMessage(err));
    }
  }

  // 7) Runtime (+ Runner ≈ Runtime)
  mark("RUNTIME_START", "RUNNING");
  if (snap.runtime === "RUNNING") {
    mark("RUNTIME_START", "PASS", "already RUNNING");
  } else {
    try {
      await deps.startRuntime(CONFIRM_START_RUNTIME);
      mark("RUNTIME_START", "PASS");
    } catch (err) {
      return fail("RUNTIME_START", errMessage(err));
    }
  }

  // 최종 스냅샷 재조회 (실패해도 기동 결과는 PASS 유지, 스냅샷만 null 가능)
  try {
    snapshot = snapshotFromOpsStatus(await deps.fetchOpsStatus());
  } catch {
    // ignore refresh errors
  }

  return {
    ok: true,
    failedStep: null,
    failedReason: null,
    steps,
    snapshot,
  };
}
