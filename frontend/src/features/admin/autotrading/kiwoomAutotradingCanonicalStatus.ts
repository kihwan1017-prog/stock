/**
 * KIWOOM Admin 자동매매 — ops-status HTTP SoT canonical 표시.
 * UPBIT 전용 /readiness API는 Kiwoom 준비상태 SoT로 사용하지 않는다.
 */

import { autoTradingStateLabelKo } from "@/features/admin/autotrading/slotStatusLabels";
import type { StatusTone } from "@/features/admin/autotrading/statusTone";
import { asRecordOrEmpty } from "@/shared/utils/dataHelpers";

export type TriStateOnOff = "on" | "off" | "unknown";

export function parseTriStateOnOff(value: unknown): TriStateOnOff {
  if (value == null || value === "") return "unknown";
  const normalized = String(value).trim().toUpperCase();
  if (normalized === "ON" || normalized === "TRUE" || normalized === "1") {
    return "on";
  }
  if (normalized === "OFF" || normalized === "FALSE" || normalized === "0") {
    return "off";
  }
  return "unknown";
}

export function isLiveOn(ops: unknown): TriStateOnOff {
  return parseTriStateOnOff(asRecordOrEmpty(ops).live);
}

export function isArmOn(ops: unknown): TriStateOnOff {
  return parseTriStateOnOff(asRecordOrEmpty(ops).arm);
}

export function liveDisplayLabel(state: TriStateOnOff): string {
  if (state === "on") return "켜짐";
  if (state === "off") return "꺼짐";
  return "확인 불가";
}

export function armDisplayLabel(state: TriStateOnOff): string {
  if (state === "on") return "승인";
  if (state === "off") return "해제";
  return "확인 불가";
}

export function toneFromTriStateOnOff(state: TriStateOnOff): StatusTone {
  if (state === "on") return "green";
  if (state === "off") return "gray";
  return "gray";
}

/** runtime_stack.label 우선, 없으면 running_count/total */
export function getRuntimeStackLabel(ops: unknown): string {
  const root = asRecordOrEmpty(ops);
  const stack = asRecordOrEmpty(root.runtime_stack);
  const label = stack.label;
  if (label != null && String(label).trim() !== "") {
    return String(label);
  }
  const running = stack.running_count;
  const total = stack.total;
  if (running != null && total != null) {
    return `${running}/${total}`;
  }
  return "확인 불가";
}

function kiwoomBlockerLabelKo(code: string): string {
  const map: Record<string, string> = {
    LIVE_OFF: "LIVE 비활성",
    ARM_OFF: "ARM 비활성",
    ARM_OFF_OR_EXPIRED: "ARM 만료",
    ACTIVATION_INACTIVE: "세션 활성화 만료",
    MARKET_FEED_UNHEALTHY: "시세 피드 장애",
    EXECUTION_STACK_DOWN: "실행 스택 중단",
    PARTIAL_RESTORE: "실행 스택 불완전",
  };
  return map[code] ?? code;
}

/** Kiwoom 준비상태 — ops-status only (UPBIT readiness 무시) */
export function getKiwoomReadyDisplay(ops: unknown): {
  label: string;
  toneSource: string;
} {
  const root = asRecordOrEmpty(ops);
  if (root.auto_trading_ready === true || root.ready === true) {
    return { label: "준비 완료", toneSource: "READY" };
  }
  const autoState = String(root.auto_trading_state ?? "").toUpperCase();
  if (autoState === "RUNNING") {
    return { label: "자동매매 가동 중", toneSource: "RUNNING" };
  }
  const blocker =
    root.primary_blocker != null
      ? String(root.primary_blocker)
      : Array.isArray(root.blockers) && root.blockers.length > 0
        ? String(root.blockers[0] ?? "")
        : "";
  if (blocker) {
    return {
      label: `차단: ${kiwoomBlockerLabelKo(blocker)}`,
      toneSource: "BLOCKED",
    };
  }
  if (autoState) {
    return {
      label: autoTradingStateLabelKo(autoState),
      toneSource: autoState,
    };
  }
  return { label: "확인 불가", toneSource: "UNKNOWN" };
}

/**
 * LEASE 표시 — MARKET_HOURS vs 24H 구분.
 * ACTIVE 상태와 mode 라벨을 분리한다.
 */
export function getKiwoomLeaseDisplay(ops: unknown): string {
  const root = asRecordOrEmpty(ops);
  const unattended = asRecordOrEmpty(root.unattended);
  const statusCode = String(
    unattended.status_code ??
      unattended.lease_status ??
      unattended.status ??
      "",
  ).toUpperCase();
  const leaseActive =
    statusCode === "ACTIVE" || unattended.entry_lease_active === true;

  if (!leaseActive) {
    if (statusCode === "PROTECTIVE_EXIT_ONLY") {
      return "신규 진입 중지 · 기존 포지션 보호만 수행";
    }
    if (statusCode === "EXPIRED") return "무인운영 만료";
    if (statusCode === "DISABLED" || statusCode === "OFF") {
      return "무인운영 꺼짐";
    }
    return statusCode ? `무인운영 ${statusCode}` : "확인 불가";
  }

  const mode = String(
    unattended.authorization_mode ?? unattended.authorizationMode ?? "",
  ).toUpperCase();
  if (mode === "MARKET_HOURS" || mode.includes("MARKET_HOURS")) {
    return "장중 무인운영 활성";
  }
  if (
    mode === "HOURS_24" ||
    mode === "24H" ||
    mode.includes("24H") ||
    mode.includes("HOURS_24")
  ) {
    return "24H 무인운영 활성";
  }
  return "무인운영 활성";
}

export function getKiwoomLeaseTone(ops: unknown): StatusTone {
  const root = asRecordOrEmpty(ops);
  const unattended = asRecordOrEmpty(root.unattended);
  const statusCode = String(
    unattended.status_code ?? unattended.lease_status ?? "",
  ).toUpperCase();
  if (
    statusCode === "ACTIVE" ||
    unattended.entry_lease_active === true
  ) {
    return "green";
  }
  if (statusCode === "PROTECTIVE_EXIT_ONLY") return "yellow";
  if (statusCode === "EXPIRED" || statusCode === "DISABLED") return "gray";
  return "gray";
}

/** UPBIT readiness가 BLOCKED여도 Kiwoom ops ready=true면 준비 완료 (회귀 방지) */
export function resolveKiwoomReadyLabel(
  ops: unknown,
  _upbitReadinessBlocked?: unknown,
): string {
  return getKiwoomReadyDisplay(ops).label;
}
