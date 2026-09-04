/**
 * 자동매매 차단 provenance 표시 헬퍼 (ops.block_history + kill_switch).
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

export type BlockHistoryView = {
  status: "BLOCKED" | "RESOLVED" | "NONE";
  blockedAt: string | null;
  unblockedAt: string | null;
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
  if (h > 0) return `${h}시간 ${m}분`;
  if (m > 0) return `${m}분`;
  return `${sec}초`;
}

export function parseBlockHistoryView(ops: unknown): BlockHistoryView {
  const root = asRecordOrEmpty(ops);
  const hist = asRecordOrEmpty(root.block_history);
  const kill = asRecordOrEmpty(root.kill_switch);
  const statusRaw = String(hist.status ?? "NONE").toUpperCase();
  const status =
    statusRaw === "BLOCKED" || statusRaw === "RESOLVED" ? statusRaw : "NONE";

  let blockedAt =
    hist.blocked_at != null
      ? String(hist.blocked_at)
      : kill.activated_at != null
        ? String(kill.activated_at)
        : null;
  const unblockedAt =
    hist.unblocked_at != null
      ? String(hist.unblocked_at)
      : hist.resolved_at != null
        ? String(hist.resolved_at)
        : null;

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
    blockedAt = blockedAt ?? (kill.activated_at != null ? String(kill.activated_at) : null);
  }

  const effectiveStatus: BlockHistoryView["status"] =
    status !== "NONE"
      ? status
      : kill.active === true
        ? "BLOCKED"
        : "NONE";

  return {
    status: effectiveStatus,
    blockedAt: formatKst(blockedAt),
    unblockedAt: formatKst(unblockedAt),
    primaryCode,
    primaryText,
    secondaryCodes,
    secondaryText,
    durationLabel:
      effectiveStatus === "BLOCKED"
        ? formatBlockDuration(blockedAt)
        : formatBlockDuration(blockedAt, unblockedAt),
    killScope:
      hist.kill_switch_scope != null
        ? String(hist.kill_switch_scope)
        : kill.scope_code != null
          ? String(kill.scope_code)
          : null,
    killReason,
    resolutionType:
      hist.resolution_type != null ? String(hist.resolution_type) : null,
  };
}
