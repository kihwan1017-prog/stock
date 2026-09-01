/**
 * UPBIT 자동매매 Admin — ops-status / readiness canonical 표시.
 * LIVE/ARM은 ops-status `live`/`arm` 문자열이 SoT (계좌 현황과 동일).
 *
 * operational_tier (서버 SoT):
 *   RUNNING | ENTRY_RESTRICTED | SYSTEM_BLOCKED
 */

import { buildOpsStatusSummary } from "@/features/admin/accounts/opsStatusSummary";
import { asRecordOrEmpty } from "@/shared/utils/dataHelpers";

export type UpbitAutotradingAggregateTier =
  | "running"
  | "entry_restricted"
  | "system_blocked"
  | "available_waiting"
  | "blocked";

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
  operationalTier?: string;
  systemBlocked?: boolean;
  entryRestricted?: boolean;
};

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function parseOperationalSemantics(ops: unknown): Record<string, unknown> {
  const root = asRecordOrEmpty(ops);
  const rel = asRecordOrEmpty(root.reliability);
  const sem = asRecordOrEmpty(root.operational_semantics ?? rel.operational_semantics);
  return sem;
}

/** ops-status payload — `live`/`arm` ON|OFF (서버 SoT) */
export function parseOpsLiveArm(ops: unknown): {
  liveOn: boolean;
  armOn: boolean;
  liveLabel: string;
  armLabel: string;
  armExpiresAt: string | null;
} {
  const root = asRecordOrEmpty(ops);
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
  const opsRoot = asRecordOrEmpty(ops);
  const readyRoot = asRecordOrEmpty(readiness);
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

function blockerLabelKo(code: string): string {
  const map: Record<string, string> = {
    LIVE_OFF: "LIVE 비활성",
    ARM_OFF: "ARM 비활성",
    ARM_OFF_OR_EXPIRED: "ARM 만료",
    ACTIVATION_INACTIVE: "세션 활성화 만료",
    KILL_SWITCH_ACTIVE: "Kill Switch",
    PARTIAL_RESTORE: "실행 스택 불완전",
    MARKET_FEED_UNHEALTHY: "시세 피드 장애",
    EXECUTION_STACK_DOWN: "실행 스택 중단",
    RECOVERY_CONFLICT: "복구 충돌",
    AMBIGUOUS_ORDER: "주문 상태 불명확",
    EXIT_PENDING_ZERO_FILL_STUCK: "청산 주문 체결 대기",
  };
  return map[code] ?? code;
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
  const opsRoot = asRecordOrEmpty(input.ops);
  const rel = asRecordOrEmpty(opsRoot.reliability);
  const sem = parseOperationalSemantics(input.ops);
  const operationalTier = String(
    sem.operational_tier ?? opsRoot.operational_tier ?? "",
  ).toUpperCase();
  const healthState = String(rel.health_state ?? "").toUpperCase();
  const readyRoot = asRecordOrEmpty(input.readiness);
  const readinessStatus = String(
    readyRoot.status ?? readyRoot.readiness ?? "—",
  ).toUpperCase();
  const entryEvaluatorState = String(
    input.entryEvaluatorState ?? "—",
  ).toUpperCase();
  const blockers = mergeAutotradingBlockers(input.ops, input.readiness);

  const readinessReady = readinessStatus === "READY_FOR_AUTO_TRADING";
  const informationalFirstZero = sem.informational_first_zero === true;

  const noTradeClass = String(rel.no_trade_classification ?? "").toUpperCase();
  const waitingStarvation = rel.waiting_starvation as Record<string, unknown> | undefined;
  const healthReasons = Array.isArray(rel.health_reasons)
    ? rel.health_reasons.map((x) => String(x ?? "").toUpperCase())
    : [];
  const isWaitingStarvationBroken = healthReasons.includes(
    "WAITING_SLOT_STARVATION_BROKEN",
  );
  const isWaitingStarvation =
    isWaitingStarvationBroken ||
    noTradeClass === "WAITING_SLOT_STARVATION" ||
    (waitingStarvation?.waiting_slot_starvation === true &&
      (noTradeClass === "PIPELINE_STALL" ||
        noTradeClass === "WAITING_SLOT_STARVATION" ||
        healthState === "BROKEN" ||
        healthState === "DEGRADED"));

  const firstZero =
    rel.first_zero_stage != null ? String(rel.first_zero_stage) : null;
  const firstZeroReason =
    rel.first_zero_reason != null ? String(rel.first_zero_reason) : null;
  const funnelDiag =
    firstZero != null && !informationalFirstZero
      ? ` Funnel FIRST_ZERO=${firstZero}${
          firstZeroReason ? ` (${firstZeroReason})` : ""
        }.`
      : firstZero != null && informationalFirstZero
        ? ` (Funnel: ${firstZeroReason ?? firstZero} — 참고용)`
        : "";

  const baseMeta = {
    blockers,
    liveOn,
    armOn,
    readinessStatus,
    entryEvaluatorState,
    operationalTier,
    systemBlocked: operationalTier === "SYSTEM_BLOCKED",
    entryRestricted: operationalTier === "ENTRY_RESTRICTED",
  };

  // 서버 operational semantics 우선
  if (operationalTier === "ENTRY_RESTRICTED") {
    const primaryKo = String(
      sem.primary_blocker_ko ?? "청산 주문 체결 대기",
    );
    return {
      ...baseMeta,
      tier: "entry_restricted",
      headline: "청산 주문 체결 대기",
      description:
        `기존 청산 주문은 정상 처리 중입니다. 신규 매수는 안전상 일시 제한됩니다. ` +
        `체결 또는 종료되면 자동으로 해제됩니다. (${primaryKo})${funnelDiag}`,
      entryOrdersPermitted: false,
    };
  }

  if (operationalTier === "RUNNING") {
    const evaluatorNote =
      entryEvaluatorState === "RUNNING"
        ? "매수조건 평가기가 후보를 평가 중입니다. 슬롯별 진입 조건 미충족 시 주문은 발생하지 않습니다."
        : "스택 가동 중 — 매수 조건 충족 시 주문이 실행됩니다.";
    return {
      ...baseMeta,
      tier: readinessReady ? "available_waiting" : "running",
      headline: readinessReady
        ? "자동매매 가능 · 매수조건 대기"
        : "자동매매 정상",
      description: evaluatorNote + funnelDiag,
      blockers: [],
      entryOrdersPermitted: readinessReady && liveOn && armOn,
    };
  }

  // 1) 진짜 PARTIAL_RESTORE만 스택 장애로 표시
  if (rel.partial_restore === true) {
    return {
      ...baseMeta,
      tier: "system_blocked",
      headline: "자동매매 차단",
      description: `실행 스택 불완전 (PARTIAL_RESTORE). Watchdog 자동복구 중이거나 관리자 확인이 필요합니다.${funnelDiag}`,
      entryOrdersPermitted: false,
    };
  }

  // 2) Waiting 슬롯 포화
  if (isWaitingStarvation) {
    const wc =
      rel.waiting_count ??
      (waitingStarvation?.waiting_count as number | undefined) ??
      "—";
    const oldestRaw =
      (waitingStarvation?.oldest_waiting_age_seconds as number | undefined) ??
      (rel.heartbeats != null &&
      typeof rel.heartbeats === "object" &&
      (rel.heartbeats as Record<string, unknown>).oldest_waiting_age_seconds !=
        null
        ? Number(
            (rel.heartbeats as Record<string, unknown>)
              .oldest_waiting_age_seconds,
          )
        : null);
    const oldestMin =
      oldestRaw != null && Number.isFinite(Number(oldestRaw))
        ? Math.round(Number(oldestRaw) / 60)
        : null;
    return {
      ...baseMeta,
      tier: "system_blocked",
      headline: "🟡 자동매매 후보 대기 슬롯 포화",
      description:
        `대기 후보가 기술조건 미충족 상태로 장시간 슬롯을 점유하고 있습니다. ` +
        `실행 프로세스는 정상이며 신규 후보 등록이 제한될 수 있습니다. ` +
        `(WAITING ${String(wc)}${
          oldestMin != null ? ` · 최장 ${oldestMin}분` : ""
        }).${funnelDiag}`,
      entryOrdersPermitted: false,
    };
  }

  if (healthState === "BROKEN") {
    const reasonKo = healthReasons.map(blockerLabelKo).join(", ");
    return {
      ...baseMeta,
      tier: "system_blocked",
      headline: "자동매매 차단",
      description: `운영 상태 이상 (${reasonKo || "reason unknown"}).${funnelDiag}`,
      entryOrdersPermitted: false,
    };
  }

  if (healthState === "DEGRADED" && !informationalFirstZero) {
    const onlyExitPending =
      healthReasons.length === 1 &&
      healthReasons[0] === "EXIT_PENDING_ZERO_FILL_STUCK";
    if (onlyExitPending && liveOn && armOn) {
      return {
        ...baseMeta,
        tier: "entry_restricted",
        headline: "청산 주문 체결 대기",
        description:
          "기존 청산 주문은 정상 처리 중입니다. 신규 매수는 안전상 일시 제한됩니다. " +
          "체결 또는 종료되면 자동으로 해제됩니다." +
          funnelDiag,
        entryOrdersPermitted: false,
      };
    }
    return {
      ...baseMeta,
      tier: "system_blocked",
      headline: "자동매매 차단",
      description: `운영 상태 degraded — ${String(rel.no_trade_classification ?? summary.primaryBlocker ?? "확인 필요")}${funnelDiag}`,
      entryOrdersPermitted: false,
    };
  }

  if (!liveOn || !armOn) {
    const gateBlockers = [
      !liveOn ? "LIVE_OFF" : null,
      !armOn ? "ARM_OFF_OR_EXPIRED" : null,
    ].filter((x): x is string => Boolean(x));
    const labels = gateBlockers.map(blockerLabelKo).join(", ");
    return {
      ...baseMeta,
      tier: "system_blocked",
      headline: "자동매매 차단",
      description:
        `실거래(LIVE) 또는 자동주문 승인(ARM)이 꺼져 있습니다 (${labels}). ` +
        "매수조건 평가기·런타임이 실행 중이어도 실제 매수 주문은 발생하지 않습니다.",
      blockers: gateBlockers.length ? gateBlockers : blockers,
      entryOrdersPermitted: false,
    };
  }

  if (
    !readinessReady ||
    blockers.some((b) => !b.startsWith("AI_") && !informationalFirstZero)
  ) {
    const primary =
      summary.primaryBlocker ??
      blockers.find((b) => !b.startsWith("AI_")) ??
      blockers[0] ??
      readinessStatus;
    if (informationalFirstZero && liveOn && armOn) {
      return {
        ...baseMeta,
        tier: "running",
        headline: "자동매매 정상",
        description: `Funnel 참고: ${firstZeroReason ?? firstZero ?? "—"}`,
        blockers: [],
        entryOrdersPermitted: false,
      };
    }
    return {
      ...baseMeta,
      tier: "system_blocked",
      headline: "자동매매 차단",
      description: `Readiness 또는 운영 게이트 미충족: ${blockerLabelKo(String(primary))}`,
      entryOrdersPermitted: false,
    };
  }

  const evaluatorNote =
    entryEvaluatorState === "RUNNING"
      ? "매수조건 평가기가 후보를 평가 중입니다. 슬롯별 진입 조건 미충족 시 주문은 발생하지 않습니다."
      : "스택 가동 중 — 매수 조건 충족 시 주문이 실행됩니다.";

  return {
    ...baseMeta,
    tier: "available_waiting",
    headline: "자동매매 가능 · 매수조건 대기",
    description: evaluatorNote,
    blockers: [],
    entryOrdersPermitted: true,
  };
}
