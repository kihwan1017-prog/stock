/**
 * UPBIT 24H 운영 스택 fail-closed 오케스트레이터.
 * LIVE/ARM/Activation 은 강한 승인 경로에서만 켜고,
 * 여기서는 Worker / Exit Monitor / Runtime 만 canonical API로 제어한다.
 */

import {
  CONFIRM_START_EXIT_MONITOR,
  CONFIRM_START_RUNTIME,
  CONFIRM_START_WORKER,
  CONFIRM_STOP_EXIT_MONITOR,
  CONFIRM_STOP_RUNTIME,
  CONFIRM_STOP_WORKER,
} from "./upbit24x7Confirmations";

export type StackStartStepId =
  | "PREFLIGHT"
  | "GATE_ACTIVATION"
  | "GATE_LIVE"
  | "GATE_ARM"
  | "WORKER_START"
  | "EXIT_MONITOR_START"
  | "RUNTIME_START";

export type StackStopStepId =
  | "PREFLIGHT"
  | "RUNTIME_STOP"
  | "EXIT_MONITOR_STOP"
  | "WORKER_STOP";

export type StackStepId = StackStartStepId | StackStopStepId;

export type StackStartStepStatus =
  | "PENDING"
  | "RUNNING"
  | "PASS"
  | "FAIL"
  | "SKIPPED";

export type StackStartStepResult = {
  id: StackStepId;
  status: StackStartStepStatus;
  reason?: string;
};

export type StackStartSnapshot = {
  live: string;
  arm: string;
  activation: string;
  armRemainingLabel: string;
  activationRemainingLabel: string;
  runtime: string;
  runner: string;
  outboxWorker: string;
  exitMonitor: string;
  autoTradingState: string;
  unattendedEnabled: boolean;
  unattendedRemainingLabel: string;
  unattendedStatusCode: string;
  needsReauthorize: boolean;
  unattendedAuthorizedUntil: string | null;
  entryAuthorized: boolean;
  stackLabel: string;
  aiState: string;
  blockers: string[];
  primaryBlocker: string | null;
};

export type StackStartOutcome = {
  ok: boolean;
  failedStep: StackStepId | null;
  failedReason: string | null;
  steps: StackStartStepResult[];
  snapshot: StackStartSnapshot | null;
};

export type StackStartDeps = {
  fetchOpsStatus: () => Promise<unknown>;
  startWorker: (confirmationText: string) => Promise<unknown>;
  startExitMonitor: (confirmationText: string) => Promise<unknown>;
  startRuntime: (confirmationText: string) => Promise<unknown>;
};

export type StackStopDeps = {
  fetchOpsStatus: () => Promise<unknown>;
  stopWorker: (confirmationText: string) => Promise<unknown>;
  stopExitMonitor: (confirmationText: string) => Promise<unknown>;
  stopRuntime: (confirmationText: string) => Promise<unknown>;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function formatRemainingSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
  return `${m}m`;
}

export function snapshotFromOpsStatus(payload: unknown): StackStartSnapshot {
  const root = asRecord(payload);
  const stack = asRecord(root.runtime_stack);
  const unattended = asRecord(root.unattended);
  const remUnatt = Number(unattended.remaining_seconds ?? 0);
  const statusCode = String(unattended.status_code ?? "OFF").toUpperCase();
  const entryAuthorized = Boolean(unattended.entry_authorized);
  const needsReauthorize =
    unattended.needs_reauthorize != null
      ? Boolean(unattended.needs_reauthorize)
      : !(
          Boolean(unattended.unattended_enabled) &&
          statusCode === "ACTIVE" &&
          entryAuthorized &&
          remUnatt > 0
        );
  const unattOn =
    Boolean(unattended.unattended_enabled) &&
    !needsReauthorize &&
    statusCode === "ACTIVE";
  return {
    live: String(root.live ?? "OFF").toUpperCase(),
    arm: String(root.arm ?? "OFF").toUpperCase(),
    activation: String(root.activation ?? "INACTIVE").toUpperCase(),
    armRemainingLabel: String(
      root.arm_remaining_label ??
        formatRemainingSeconds(Number(root.arm_remaining_seconds ?? 0)),
    ),
    activationRemainingLabel: String(
      root.activation_remaining_label ??
        formatRemainingSeconds(Number(root.activation_remaining_seconds ?? 0)),
    ),
    runtime: String(root.runtime ?? stack.runtime ?? "STOPPED").toUpperCase(),
    runner: String(root.runner ?? stack.runner ?? "STOPPED").toUpperCase(),
    outboxWorker: String(
      root.outbox_worker ?? stack.outbox_worker ?? "STOPPED",
    ).toUpperCase(),
    exitMonitor: String(
      root.exit_monitor ?? stack.exit_monitor ?? "STOPPED",
    ).toUpperCase(),
    autoTradingState: String(root.auto_trading_state ?? "STOPPED").toUpperCase(),
    unattendedEnabled: unattOn,
    unattendedRemainingLabel: unattOn
      ? formatRemainingSeconds(remUnatt)
      : "—",
    unattendedStatusCode: statusCode || "OFF",
    needsReauthorize,
    unattendedAuthorizedUntil:
      unattended.authorized_until != null
        ? String(unattended.authorized_until)
        : null,
    entryAuthorized,
    stackLabel: String(stack.label ?? "0/4"),
    aiState: String(root.ai_state ?? "HOLD").toUpperCase(),
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

const START_STEP_ORDER: StackStartStepId[] = [
  "PREFLIGHT",
  "GATE_ACTIVATION",
  "GATE_LIVE",
  "GATE_ARM",
  "WORKER_START",
  "EXIT_MONITOR_START",
  "RUNTIME_START",
];

const STOP_STEP_ORDER: StackStopStepId[] = [
  "PREFLIGHT",
  "RUNTIME_STOP",
  "EXIT_MONITOR_STOP",
  "WORKER_STOP",
];

/**
 * Preflight/gate 통과 후 Worker → Exit → Runtime 순 기동.
 * 어느 단계든 실패 시 즉시 중단(FAIL CLOSED).
 */
export async function runUpbit24x7StackStart(
  deps: StackStartDeps,
): Promise<StackStartOutcome> {
  const steps: StackStartStepResult[] = START_STEP_ORDER.map((id) => ({
    id,
    status: "PENDING",
  }));

  const mark = (
    id: StackStepId,
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

  const fail = (id: StackStepId, reason: string): StackStartOutcome => {
    mark(id, "FAIL", reason);
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

  mark("PREFLIGHT", "RUNNING");
  try {
    snapshot = snapshotFromOpsStatus(await deps.fetchOpsStatus());
    mark("PREFLIGHT", "PASS");
  } catch (err) {
    return fail("PREFLIGHT", errMessage(err));
  }

  if (!snapshot) {
    return fail("PREFLIGHT", "ops-status snapshot missing");
  }
  const snap = snapshot;

  mark("GATE_ACTIVATION", "RUNNING");
  if (snap.activation !== "ACTIVE") {
    return fail(
      "GATE_ACTIVATION",
      `Activation이 ACTIVE가 아닙니다 (현재: ${snap.activation}).`,
    );
  }
  mark("GATE_ACTIVATION", "PASS");

  mark("GATE_LIVE", "RUNNING");
  if (snap.live !== "ON") {
    return fail("GATE_LIVE", "LIVE OFF — LIVE 패널에서 켠 뒤 재시도하세요.");
  }
  mark("GATE_LIVE", "PASS");

  mark("GATE_ARM", "RUNNING");
  if (snap.arm !== "ON") {
    return fail("GATE_ARM", "ARM OFF — LIVE 패널에서 승인 후 수행하세요.");
  }
  mark("GATE_ARM", "PASS");

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

  try {
    snapshot = snapshotFromOpsStatus(await deps.fetchOpsStatus());
  } catch {
    // ignore
  }

  return {
    ok: true,
    failedStep: null,
    failedReason: null,
    steps,
    snapshot,
  };
}

/**
 * Runtime → Exit → Worker 순 중지 (START 역순).
 * LIVE / ARM / Unattended 는 변경하지 않는다.
 */
export async function runUpbit24x7StackStop(
  deps: StackStopDeps,
): Promise<StackStartOutcome> {
  const steps: StackStartStepResult[] = STOP_STEP_ORDER.map((id) => ({
    id,
    status: "PENDING",
  }));

  const mark = (
    id: StackStepId,
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

  const fail = (id: StackStepId, reason: string): StackStartOutcome => {
    mark(id, "FAIL", reason);
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

  mark("PREFLIGHT", "RUNNING");
  try {
    snapshot = snapshotFromOpsStatus(await deps.fetchOpsStatus());
    mark("PREFLIGHT", "PASS");
  } catch (err) {
    return fail("PREFLIGHT", errMessage(err));
  }

  if (!snapshot) {
    return fail("PREFLIGHT", "ops-status snapshot missing");
  }
  const snap = snapshot;

  mark("RUNTIME_STOP", "RUNNING");
  if (snap.runtime !== "RUNNING" && snap.runtime !== "PAUSED") {
    mark("RUNTIME_STOP", "PASS", `already ${snap.runtime}`);
  } else {
    try {
      await deps.stopRuntime(CONFIRM_STOP_RUNTIME);
      mark("RUNTIME_STOP", "PASS");
    } catch (err) {
      return fail("RUNTIME_STOP", errMessage(err));
    }
  }

  mark("EXIT_MONITOR_STOP", "RUNNING");
  if (snap.exitMonitor !== "RUNNING") {
    mark("EXIT_MONITOR_STOP", "PASS", `already ${snap.exitMonitor}`);
  } else {
    try {
      await deps.stopExitMonitor(CONFIRM_STOP_EXIT_MONITOR);
      mark("EXIT_MONITOR_STOP", "PASS");
    } catch (err) {
      return fail("EXIT_MONITOR_STOP", errMessage(err));
    }
  }

  mark("WORKER_STOP", "RUNNING");
  if (snap.outboxWorker !== "RUNNING") {
    mark("WORKER_STOP", "PASS", `already ${snap.outboxWorker}`);
  } else {
    try {
      await deps.stopWorker(CONFIRM_STOP_WORKER);
      mark("WORKER_STOP", "PASS");
    } catch (err) {
      return fail("WORKER_STOP", errMessage(err));
    }
  }

  try {
    snapshot = snapshotFromOpsStatus(await deps.fetchOpsStatus());
  } catch {
    // ignore
  }

  return {
    ok: true,
    failedStep: null,
    failedReason: null,
    steps,
    snapshot,
  };
}
