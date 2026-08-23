/**
 * UPBIT 자동매매 Admin — ops-status / readiness canonical 표시.
 * LIVE/ARM은 ops-status `live`/`arm` 문자열이 SoT (계좌 현황과 동일).
 */

import { buildOpsStatusSummary } from "@/features/admin/accounts/opsStatusSummary";
import { asRecord } from "@/shared/utils/dataHelpers";

export type UpbitAutotradingAggregateTier = "available_waiting" | "blocked";

export type UpbitAutotradingAggregateStatus = {
  tier: UpbitAutotradingAggregateTier;
  headline: string;
  description: string;
  blockers: string[];
  liveOn: boolean;
  armOn: boolean;
  readinessStatus: string;
  entryEvaluatorState: string;
  /** Evaluator RUNNING이어도 LIVE/ARM/Readiness 미충족 시 false */
  entryOrdersPermitted: boolean;
};

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** ops-status payload — `live`/`arm` ON|OFF (서버 SoT) */
export function parseOpsLiveArm(ops: unknown): {
  liveOn: boolean;
  armOn: boolean;
  liveLabel: string;
  armLabel: string;
  armExpiresAt: string | null;
} {
  const root = asRecord(ops);
  const liveOn = String(root.live ?? "OFF").toUpperCase() === "ON";
  const armOn = String(root.arm ?? "OFF").toUpperCase() === "ON";
  const summary = buildOpsStatusSummary(ops);
  return {
    liveOn,
    armOn,
    liveLabel: summary.liveLabel,
    armLabel: summary.armLabel,
    armExpiresAt:
      root.arm_expires_at != null ? String(root.arm_expires_at) : null,
  };
}

/** readiness + ops blockers 병합 (LIVE/ARM은 ops SoT 우선) */
export function mergeAutotradingBlockers(
  ops: unknown,
  readiness?: unknown,
): string[] {
  const { liveOn, armOn } = parseOpsLiveArm(ops);
  const opsRoot = asRecord(ops);
  const readyRoot = asRecord(readiness);
  const merged = new Set<string>();

  if (!liveOn) merged.add("LIVE_OFF");
  if (!armOn) merged.add("ARM_OFF_OR_EXPIRED");

  for (const code of asArray(opsRoot.blockers)) {
    const s = String(code ?? "").trim();
    if (s) merged.add(s);
  }
  for (const code of asArray(readyRoot.blockers)) {
    const s = String(code ?? "").trim();
    if (s) merged.add(s);
  }
  return [...merged];
}

/**
 * 화면 최상단 종합 상태.
 * Evaluator RUNNING ≠ 실제 ENTRY 주문 가능.
 */
export function buildUpbitAutotradingAggregateStatus(input: {
  ops: unknown;
  readiness?: unknown;
  entryEvaluatorState?: unknown;
}): UpbitAutotradingAggregateStatus {
  const { liveOn, armOn } = parseOpsLiveArm(input.ops);
  const summary = buildOpsStatusSummary(input.ops);
  const readyRoot = asRecord(input.readiness);
  const readinessStatus = String(
    readyRoot.status ?? readyRoot.readiness ?? "—",
  ).toUpperCase();
  const entryEvaluatorState = String(
    input.entryEvaluatorState ?? "—",
  ).toUpperCase();
  const blockers = mergeAutotradingBlockers(input.ops, input.readiness);

  const readinessReady = readinessStatus === "READY_FOR_AUTO_TRADING";
  const entryOrdersPermitted =
    liveOn && armOn && readinessReady && blockers.length === 0;

  if (!liveOn || !armOn) {
    const gateBlockers = [
      !liveOn ? "LIVE_OFF" : null,
      !armOn ? "ARM_OFF_OR_EXPIRED" : null,
    ].filter((x): x is string => Boolean(x));
    return {
      tier: "blocked",
      headline: "자동매매 차단",
      description:
        "실거래(LIVE) 또는 자동주문 승인(ARM)이 꺼져 있습니다. 매수조건 평가기·런타임이 실행 중이어도 실제 매수 주문은 발생하지 않습니다.",
      blockers: gateBlockers.length ? gateBlockers : blockers,
      liveOn,
      armOn,
      readinessStatus,
      entryEvaluatorState,
      entryOrdersPermitted: false,
    };
  }

  if (!readinessReady || blockers.some((b) => !b.startsWith("AI_"))) {
    const primary =
      summary.primaryBlocker ??
      blockers.find((b) => !b.startsWith("AI_")) ??
      blockers[0] ??
      readinessStatus;
    return {
      tier: "blocked",
      headline: "자동매매 차단",
      description: `Readiness 또는 운영 게이트 미충족: ${primary}`,
      blockers,
      liveOn,
      armOn,
      readinessStatus,
      entryEvaluatorState,
      entryOrdersPermitted: false,
    };
  }

  const evaluatorNote =
    entryEvaluatorState === "RUNNING"
      ? "매수조건 평가기가 후보를 평가 중입니다. 슬롯별 진입 조건 미충족 시 주문은 발생하지 않습니다."
      : "스택 가동 중 — 매수 조건 충족 시 주문이 실행됩니다.";

  return {
    tier: "available_waiting",
    headline: "자동매매 가능 · 매수조건 대기",
    description: evaluatorNote,
    blockers: [],
    liveOn,
    armOn,
    readinessStatus,
    entryEvaluatorState,
    entryOrdersPermitted: true,
  };
}
