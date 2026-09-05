/**
 * 자동매매 차단 provenance 표시 헬퍼 (ops.block_history + kill_switch).
 * 차단 일시 ≠ Activation/ARM refresh 시각 — 복구 lifecycle은 block_event SoT.
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

export type RecoveryResult =
  | "SUCCESS"
  | "FAILED"
  | "PENDING"
  | "NOT_ATTEMPTED";

export type RecoveryMethod = "AUTO" | "MANUAL" | "MIXED" | "NOT_ATTEMPTED" | "UNKNOWN";

export type BlockHistoryView = {
  status: "BLOCKED" | "RESOLVED" | "NONE";
  blockedAt: string | null;
  unblockedAt: string | null;
  recoveryStartedAt: string | null;
  recoveredAt: string | null;
  recoveryResult: RecoveryResult;
  recoveryResultLabel: string;
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

function parseRecoveryResult(raw: unknown, status: string): RecoveryResult {
  const u = String(raw ?? "").toUpperCase();
  if (u === "SUCCESS" || u === "FAILED" || u === "PENDING" || u === "NOT_ATTEMPTED") {
    return u;
  }
  if (status === "BLOCKED") return "PENDING";
  if (status === "RESOLVED") return "SUCCESS";
  return "NOT_ATTEMPTED";
}

function parseRecoveryMethod(raw: unknown, resolutionType: string | null): RecoveryMethod {
  const u = String(raw ?? "").toUpperCase();
  if (
    u === "AUTO" ||
    u === "MANUAL" ||
    u === "MIXED" ||
    u === "NOT_ATTEMPTED" ||
    u === "UNKNOWN"
  ) {
    return u;
  }
  const res = String(resolutionType ?? "").toUpperCase();
  if (res.includes("AUTO") || res === "REASON_CHANGED" || res.includes("SELF_HEAL")) {
    return "AUTO";
  }
  if (res.includes("MANUAL") || res.includes("OPERATOR") || res.includes("ADMIN")) {
    return "MANUAL";
  }
  if (res) return "MIXED";
  return "NOT_ATTEMPTED";
}

const RESULT_LABEL: Record<RecoveryResult, string> = {
  SUCCESS: "성공",
  FAILED: "실패",
  PENDING: "진행 중",
  NOT_ATTEMPTED: "시도 안 함",
};

const METHOD_LABEL: Record<RecoveryMethod, string> = {
  AUTO: "자동",
  MANUAL: "수동",
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

  const recoveryStartedRaw =
    hist.recovery_started_at != null
      ? String(hist.recovery_started_at)
      : blockedAtRaw;
  const recoveredRaw =
    hist.recovered_at != null
      ? String(hist.recovered_at)
      : hist.resolved_at != null
        ? String(hist.resolved_at)
        : unblockedAtRaw;

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
  const recoveryResult = parseRecoveryResult(
    hist.recovery_result,
    effectiveStatus,
  );
  const recoveryMethod = parseRecoveryMethod(
    hist.recovery_method,
    resolutionType,
  );

  return {
    status: effectiveStatus,
    blockedAt: formatKst(blockedAtRaw),
    unblockedAt: formatKst(unblockedAtRaw),
    recoveryStartedAt:
      effectiveStatus === "NONE"
        ? null
        : formatKst(recoveryStartedRaw),
    recoveredAt:
      recoveryResult === "PENDING" || recoveryResult === "NOT_ATTEMPTED"
        ? null
        : formatKst(recoveredRaw),
    recoveryResult,
    recoveryResultLabel: RESULT_LABEL[recoveryResult],
    recoveryMethod,
    recoveryMethodLabel: METHOD_LABEL[recoveryMethod],
    recoveryDurationLabel:
      recoveryResult === "SUCCESS"
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
  };
}
