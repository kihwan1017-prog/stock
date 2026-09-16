/**
 * 자동매매 차단 provenance 표시 헬퍼 (ops.block_history + kill_switch).
 * scheduled / attempted / recovered 는 서로 다른 SoT — frontend에서 시각 생성 금지.
 */

import { asRecordOrEmpty } from "@/shared/utils/dataHelpers";

const PRIMARY_TEXT: Record<string, string> = {
  KILL_SWITCH_ACTIVE:
    "안전장치(Kill Switch)가 활성화되어 자동매매가 중지되었습니다.",
  LIVE_OFF: "실거래 사용 상태가 꺼져 있습니다.",
  ARM_OFF: "자동주문 승인(ARM)이 꺼져 있습니다.",
  ARM_OFF_OR_EXPIRED: "자동주문 승인(ARM)이 꺼져 있거나 만료되었습니다.",
  LIVE_NOT_APPROVED: "실거래(LIVE) 승인이 활성화되어 있지 않습니다.",
  RUNTIME_COMPONENT_STOPPED:
    "자동매매 실행 구성요소 일부가 중지되었습니다.",
  EXECUTION_STACK_DOWN: "자동매매 실행 구성요소 일부가 중지되었습니다.",
  AUTO_EXIT_QUOTE_STALE: "청산용 시세가 오래되어 안전 확인이 필요합니다.",
  NO_CANDIDATES: "현재 매수 후보가 없습니다.",
  POSITION_MISMATCH:
    "체결 후 포지션 검증에서 불일치가 감지되어 안전장치가 동작했습니다.",
};

export type RecoveryStatus =
  | "AWAITING_OPERATOR"
  | "NO_SCHEDULE"
  | "SCHEDULED"
  | "IN_PROGRESS"
  | "SUCCESS"
  | "FAILED"
  | "RETRY_WAITING"
  | "NOT_APPLICABLE";

export type RecoveryMethod =
  | "AUTO"
  | "MANUAL"
  | "OPERATOR_APPROVED"
  | "MIXED"
  | "NOT_ATTEMPTED"
  | "UNKNOWN";

export type BlockHistoryView = {
  status: "BLOCKED" | "RESOLVED" | "NONE";
  blockedAt: string | null;
  unblockedAt: string | null;
  /** 실제 scheduler next_retry 등 — 없으면 null (임의 생성 금지) */
  recoveryScheduledAt: string | null;
  /** 실제 복구 시도 시각 — blocked_at 대용 금지 */
  recoveryAttemptedAt: string | null;
  recoveredAt: string | null;
  nextRetryAt: string | null;
  recoveryStatus: RecoveryStatus;
  recoveryStatusLabel: string;
  recoveryMethod: RecoveryMethod;
  recoveryMethodLabel: string;
  recoveryDurationLabel: string | null;
  primaryCode: string | null;
  primaryText: string;
  secondaryCodes: string[];
  secondaryText: string;
  durationLabel: string | null;
  killScope: string | null;
  killReason: string | null;
  resolutionType: string | null;
  incidentId: string | null;
  recoveryClass: "A" | "B" | "C" | null;
  classificationReason: string | null;
  autoRecoveryEligible: boolean | null;
  operatorActionRequired: boolean | null;
  circuitBreakerStatus: string | null;
  recoveryAttemptCount: number | null;
  skipReason: string | null;
};

function formatKst(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
}

export function formatBlockDuration(
  fromIso: string | null,
  toIso?: string | null,
): string | null {
  if (!fromIso) return null;
  const from = new Date(fromIso).getTime();
  if (!Number.isFinite(from)) return null;
  const to = toIso ? new Date(toIso).getTime() : Date.now();
  if (!Number.isFinite(to) || to < from) return null;
  const sec = Math.floor((to - from) / 1000);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}시간 ${m}분`;
  if (m > 0) return `${m}분 ${s}초`;
  return `${s}초`;
}

function parseRecoveryMethod(
  raw: unknown,
  resolutionType: string | null,
): RecoveryMethod {
  const u = String(raw ?? "").toUpperCase();
  if (
    u === "AUTO" ||
    u === "MANUAL" ||
    u === "OPERATOR_APPROVED" ||
    u === "MIXED" ||
    u === "NOT_ATTEMPTED" ||
    u === "UNKNOWN"
  ) {
    return u;
  }
  const res = String(resolutionType ?? "").toUpperCase();
  if (res.includes("OPERATOR") || res === "OPERATOR_APPROVED") {
    return "OPERATOR_APPROVED";
  }
  if (res.includes("AUTO") || res === "REASON_CHANGED" || res.includes("SELF_HEAL")) {
    return "AUTO";
  }
  if (res.includes("MANUAL") || res.includes("ADMIN")) {
    return "MANUAL";
  }
  if (res) return "MIXED";
  return "NOT_ATTEMPTED";
}

function deriveRecoveryStatus(input: {
  status: BlockHistoryView["status"];
  scheduledRaw: string | null;
  attemptedRaw: string | null;
  recoveredRaw: string | null;
  nextRetryRaw: string | null;
  recoveryStatusRaw: string | null;
  method: RecoveryMethod;
}): RecoveryStatus {
  const raw = String(input.recoveryStatusRaw ?? "").toUpperCase();
  if (
    raw === "AWAITING_OPERATOR" ||
    raw === "NO_SCHEDULE" ||
    raw === "SCHEDULED" ||
    raw === "IN_PROGRESS" ||
    raw === "SUCCESS" ||
    raw === "FAILED" ||
    raw === "RETRY_WAITING" ||
    raw === "NOT_APPLICABLE"
  ) {
    return raw;
  }
  if (input.status === "RESOLVED" || input.recoveredRaw) return "SUCCESS";
  if (input.attemptedRaw && !input.recoveredRaw) {
    if (input.nextRetryRaw) return "RETRY_WAITING";
    return "IN_PROGRESS";
  }
  if (input.scheduledRaw || input.nextRetryRaw) return "SCHEDULED";
  if (input.status === "BLOCKED") {
    // 자동 스케줄이 없으면 운영자 승인 대기 (가짜 예정시각 생성 금지)
    return "AWAITING_OPERATOR";
  }
  return "NOT_APPLICABLE";
}

const STATUS_LABEL: Record<RecoveryStatus, string> = {
  AWAITING_OPERATOR: "운영자 승인 대기",
  NO_SCHEDULE: "자동복구 일정 없음",
  SCHEDULED: "대기 중",
  IN_PROGRESS: "복구 진행 중",
  SUCCESS: "성공",
  FAILED: "실패",
  RETRY_WAITING: "재시도 대기",
  NOT_APPLICABLE: "해당 없음",
};

const METHOD_LABEL: Record<RecoveryMethod, string> = {
  AUTO: "자동",
  MANUAL: "수동",
  OPERATOR_APPROVED: "운영자 승인 복구",
  MIXED: "혼합",
  NOT_ATTEMPTED: "시도 안 함",
  UNKNOWN: "미확인",
};

export function parseBlockHistoryView(ops: unknown): BlockHistoryView {
  const root = asRecordOrEmpty(ops);
  const hist = asRecordOrEmpty(root.block_history);
  const kill = asRecordOrEmpty(root.kill_switch);
  const statusRaw = String(hist.status ?? "NONE").toUpperCase();
  const status =
    statusRaw === "BLOCKED" || statusRaw === "RESOLVED" ? statusRaw : "NONE";

  let blockedAtRaw =
    hist.blocked_at != null
      ? String(hist.blocked_at)
      : kill.activated_at != null
        ? String(kill.activated_at)
        : null;
  const unblockedAtRaw =
    hist.unblocked_at != null
      ? String(hist.unblocked_at)
      : hist.resolved_at != null
        ? String(hist.resolved_at)
        : null;

  // 예정/시도/완료 — 존재하는 canonical 필드만 (blocked_at 대용 금지)
  const scheduledRaw =
    hist.recovery_scheduled_at != null
      ? String(hist.recovery_scheduled_at)
      : hist.next_recovery_attempt_at != null
        ? String(hist.next_recovery_attempt_at)
        : hist.next_retry_at != null
          ? String(hist.next_retry_at)
          : null;
  const attemptedRaw =
    hist.recovery_attempted_at != null
      ? String(hist.recovery_attempted_at)
      : // legacy: recovery_started_at 가 blocked_at 과 같으면 시도로 취급하지 않음
        hist.recovery_started_at != null &&
          blockedAtRaw != null &&
          String(hist.recovery_started_at) !== blockedAtRaw
        ? String(hist.recovery_started_at)
        : null;
  const recoveredRaw =
    hist.recovered_at != null
      ? String(hist.recovered_at)
      : hist.resolved_at != null
        ? String(hist.resolved_at)
        : unblockedAtRaw;
  const nextRetryRaw =
    hist.next_retry_at != null ? String(hist.next_retry_at) : null;

  const primaryCode =
    hist.primary_reason_code != null
      ? String(hist.primary_reason_code)
      : kill.active === true
        ? "KILL_SWITCH_ACTIVE"
        : root.primary_blocker != null
          ? String(root.primary_blocker)
          : null;

  const killReason =
    hist.kill_switch_reason != null
      ? String(hist.kill_switch_reason)
      : kill.reason != null
        ? String(kill.reason)
        : null;

  let primaryText =
    hist.primary_reason_text != null
      ? String(hist.primary_reason_text)
      : primaryCode
        ? PRIMARY_TEXT[primaryCode] ?? primaryCode
        : "—";
  if (
    primaryCode === "KILL_SWITCH_ACTIVE" &&
    killReason &&
    /POSITION_MISMATCH/i.test(killReason)
  ) {
    primaryText = PRIMARY_TEXT.POSITION_MISMATCH;
  }

  const secondaryCodes = Array.isArray(hist.secondary_reasons)
    ? hist.secondary_reasons.map((x) => String(x))
    : Array.isArray(root.blockers)
      ? (root.blockers as unknown[])
          .map((x) => String(x))
          .filter((c) => c && c !== primaryCode)
      : [];

  const secondaryText = secondaryCodes
    .map((c) => PRIMARY_TEXT[c] ?? c)
    .join(" · ");

  if (status === "NONE" && kill.active === true) {
    blockedAtRaw =
      blockedAtRaw ??
      (kill.activated_at != null ? String(kill.activated_at) : null);
  }

  const effectiveStatus: BlockHistoryView["status"] =
    status !== "NONE"
      ? status
      : kill.active === true
        ? "BLOCKED"
        : "NONE";

  const resolutionType =
    hist.resolution_type != null ? String(hist.resolution_type) : null;
  const recoveryMethod = parseRecoveryMethod(
    hist.recovery_method,
    resolutionType,
  );
  const recoveryStatus = deriveRecoveryStatus({
    status: effectiveStatus,
    scheduledRaw,
    attemptedRaw,
    recoveredRaw: effectiveStatus === "RESOLVED" ? recoveredRaw : null,
    nextRetryRaw,
    recoveryStatusRaw:
      hist.recovery_status != null ? String(hist.recovery_status) : null,
    method: recoveryMethod,
  });

  return {
    status: effectiveStatus,
    blockedAt: formatKst(blockedAtRaw),
    unblockedAt: formatKst(unblockedAtRaw),
    recoveryScheduledAt: formatKst(scheduledRaw),
    recoveryAttemptedAt: formatKst(attemptedRaw),
    recoveredAt:
      recoveryStatus === "SUCCESS" ? formatKst(recoveredRaw) : null,
    nextRetryAt: formatKst(nextRetryRaw),
    recoveryStatus,
    recoveryStatusLabel: STATUS_LABEL[recoveryStatus],
    recoveryMethod,
    recoveryMethodLabel: METHOD_LABEL[recoveryMethod],
    recoveryDurationLabel:
      recoveryStatus === "SUCCESS"
        ? formatBlockDuration(blockedAtRaw, recoveredRaw)
        : effectiveStatus === "BLOCKED"
          ? formatBlockDuration(blockedAtRaw)
          : null,
    primaryCode,
    primaryText,
    secondaryCodes,
    secondaryText,
    durationLabel:
      effectiveStatus === "BLOCKED"
        ? formatBlockDuration(blockedAtRaw)
        : formatBlockDuration(blockedAtRaw, unblockedAtRaw),
    killScope:
      hist.kill_switch_scope != null
        ? String(hist.kill_switch_scope)
        : kill.scope_code != null
          ? String(kill.scope_code)
          : null,
    killReason,
    resolutionType,
    incidentId: hist.incident_id != null ? String(hist.incident_id) : null,
    recoveryClass: (() => {
      const c = String(hist.recovery_class ?? "").toUpperCase();
      return c === "A" || c === "B" || c === "C" ? c : null;
    })(),
    classificationReason:
      hist.classification_reason != null
        ? String(hist.classification_reason)
        : null,
    autoRecoveryEligible:
      typeof hist.auto_recovery_eligible === "boolean"
        ? hist.auto_recovery_eligible
        : null,
    operatorActionRequired:
      typeof hist.operator_action_required === "boolean"
        ? hist.operator_action_required
        : effectiveStatus === "BLOCKED"
          ? true
          : null,
    circuitBreakerStatus:
      hist.circuit_breaker_status != null
        ? String(hist.circuit_breaker_status)
        : null,
    recoveryAttemptCount:
      hist.recovery_attempt_count != null
        ? Number(hist.recovery_attempt_count)
        : null,
    skipReason: hist.skip_reason != null ? String(hist.skip_reason) : null,
  };
}
