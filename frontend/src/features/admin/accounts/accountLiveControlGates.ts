/**
 * 계좌 LIVE 제어 UI 게이트.
 * 서버 Pre-flight/UBA 상태를 SoT로 쓰며, UI에서 조건을 완화하지 않는다.
 */

export type RuntimeAction =
  | "LIVE_ON"
  | "LIVE_OFF"
  | "ARM_ON"
  | "ARM_OFF"
  | "SCHEDULER_RUN"
  | "SCHEDULER_PAUSE";

export const SCHEDULER_RUN_DISABLED_REASON =
  "Scheduler RUN은 별도 STEP — 이번 UI에서 비활성";

export type LiveControlGateRow = {
  live_order_enabled?: unknown;
  live_armed?: unknown;
  trading_paused?: unknown;
  connection_status?: unknown;
  recovery_status?: unknown;
  active_conflict_count?: unknown;
  credential?: unknown;
  broker_code?: unknown;
};

export type LiveControlGateContext = {
  schedulerPaused: boolean;
  preflightBlocked: boolean;
  activationActive: boolean;
  /** ARM 전용 Pre-flight 차단 (없으면 LIVE_ON preflight와 동일) */
  armPreflightBlocked?: boolean;
};

function credentialInfo(row: LiveControlGateRow): {
  registered: boolean;
  verified: boolean;
} {
  const cred = row.credential;
  if (!cred || typeof cred !== "object" || Array.isArray(cred)) {
    return { registered: false, verified: false };
  }
  const rec = cred as Record<string, unknown>;
  const registered = Boolean(rec.registered);
  const status = String(rec.verification_status ?? "").toUpperCase();
  return { registered, verified: registered && status === "VERIFIED" };
}

export function isConnectionReady(row: LiveControlGateRow): boolean {
  return String(row.connection_status ?? "").toUpperCase() === "CONNECTED";
}

export function isRecoveryHealthy(row: LiveControlGateRow): boolean {
  return String(row.recovery_status ?? "").toUpperCase() === "SUCCESS";
}

export function failClosedReason(row: LiveControlGateRow): string | null {
  const cred = credentialInfo(row);
  if (!cred.registered || !cred.verified) return "Credential required";
  if (!isConnectionReady(row)) return "Disconnected";
  if (!isRecoveryHealthy(row)) return "Recovery failed";
  return null;
}

function conflictCount(row: LiveControlGateRow): number {
  const n = Number(row.active_conflict_count ?? 0);
  return Number.isFinite(n) ? n : 0;
}

/** UI gate blockers — 서버 gate보다 완화하지 않음 */
export function runtimeGateBlockers(
  action: RuntimeAction,
  row: LiveControlGateRow,
  ctx: LiveControlGateContext,
): string[] {
  const liveOn = Boolean(row.live_order_enabled);
  const armOn = Boolean(row.live_armed);
  const tradingPaused = Boolean(row.trading_paused);
  const cred = credentialInfo(row);
  const blockers: string[] = [];
  const closed = failClosedReason(row);

  if (action === "SCHEDULER_RUN") {
    blockers.push(SCHEDULER_RUN_DISABLED_REASON);
    return blockers;
  }

  if (action === "LIVE_ON") {
    if (ctx.preflightBlocked) {
      blockers.push("Pre-flight READY_FOR_LIVE+FRESH 필요 — LIVE ON 불가");
    }
    if (!ctx.activationActive) {
      blockers.push("Activation ACTIVE 필요 — LIVE ON 불가");
    }
    if (closed) blockers.push(closed);
    if (conflictCount(row) > 0) {
      blockers.push("활성 Conflict가 있어 LIVE ON 불가");
    }
    if (tradingPaused) blockers.push("거래 일시중지 상태라 LIVE ON 불가");
    if (armOn) blockers.push("ARM 상태라 LIVE ON 불가 — DISARM 후 재시도");
    if (!ctx.schedulerPaused) {
      blockers.push("Scheduler 실행 중이라 LIVE ON 불가");
    }
    if (liveOn) blockers.push("이미 LIVE ON");
  }

  if (action === "LIVE_OFF") {
    if (!liveOn) blockers.push("이미 LIVE OFF");
    if (!ctx.schedulerPaused) {
      blockers.push("Scheduler 실행 중이라 LIVE OFF 불가");
    }
    if (armOn) blockers.push("ARM 상태라 LIVE OFF 불가 — DISARM 후 재시도");
  }

  if (action === "ARM_ON") {
    const armBlocked = ctx.armPreflightBlocked ?? ctx.preflightBlocked;
    if (armBlocked) {
      blockers.push("Pre-flight ARM ready 필요 — ARM 불가");
    }
    if (!ctx.activationActive) {
      blockers.push("Activation ACTIVE 필요 — ARM 불가");
    }
    if (closed) blockers.push(closed);
    if (tradingPaused) blockers.push("거래 일시중지 상태라 ARM 불가");
    if (!liveOn) blockers.push("LIVE OFF라 ARM 불가");
    if (!ctx.schedulerPaused) {
      blockers.push("Scheduler 실행 중이라 ARM 불가");
    }
    if (armOn) blockers.push("이미 ARM ON");
  }

  if (action === "ARM_OFF") {
    if (!armOn) blockers.push("이미 DISARM");
    if (!ctx.schedulerPaused) {
      blockers.push("Scheduler 실행 중이라 DISARM 불가");
    }
  }

  if (action === "SCHEDULER_PAUSE") {
    if (ctx.schedulerPaused) blockers.push("이미 Scheduler PAUSE");
  }

  if (
    (action === "LIVE_ON" || action === "ARM_ON") &&
    !cred.verified &&
    !blockers.includes("Credential required")
  ) {
    blockers.push("Credential required");
  }

  return blockers;
}

export function schedulerIsPaused(
  status: Record<string, unknown> | undefined,
): boolean {
  if (!status) return true;
  const desired = String(
    status.desired_state ?? status.desired ?? "",
  ).toUpperCase();
  const actual = String(status.actual_state ?? status.actual ?? "").toUpperCase();
  const desiredPaused =
    desired === "PAUSE" || desired === "PAUSED" || desired === "";
  const actualPaused =
    actual === "PAUSED" ||
    actual === "PAUSE" ||
    actual === "" ||
    actual === "STOPPED";
  return desiredPaused && actualPaused;
}

export function schedulerIsRunning(
  status: Record<string, unknown> | undefined,
): boolean {
  if (!status) return false;
  const desired = String(
    status.desired_state ?? status.desired ?? "",
  ).toUpperCase();
  const actual = String(status.actual_state ?? status.actual ?? "").toUpperCase();
  return (
    desired === "RUN" ||
    desired === "RUNNING" ||
    actual === "RUNNING" ||
    actual === "RUN"
  );
}

export function buildRuntimePreflightParams(ubaId: number): {
  mode: "LIVE_ON";
  user_broker_account_id: number;
} {
  return { mode: "LIVE_ON", user_broker_account_id: ubaId };
}

export function buildArmPreflightParams(ubaId: number): {
  mode: "ARM_ON";
  user_broker_account_id: number;
} {
  return { mode: "ARM_ON", user_broker_account_id: ubaId };
}
