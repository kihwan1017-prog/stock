/**
 * Upbit 후보 슬롯 / AUTO 포지션 / 일일 진입 / 실시간 감시 — 표시 의미 분리.
 * 거래·리스크 수치를 바꾸지 않고 라벨만 정리한다.
 */

export type SlotCoverageSemanticsInput = {
  candidate_slot_assigned?: number | null;
  candidate_slot_capacity?: number | null;
  /** fallback: max_positions */
  max_positions?: number | null;
  /** fallback occupied count */
  candidates_waiting?: number | null;
  positions_open?: number | null;
  pending_orders?: number | null;
  auto_position_used?: number | null;
  auto_position_limit?: number | null;
  /** legacy alias of AUTO 보유 한도 */
  auto_slot_used?: number | null;
  auto_slot_limit?: number | null;
  daily_entry_used?: number | null;
  daily_entry_limit?: number | null;
  daily_entry_limit_mode?: string | null;
  daily_entry?: {
    entry_count?: number | null;
    entry_limit?: number | null;
    mode?: string | null;
  } | null;
  realtime_monitor_target?: number | null;
  realtime_monitored_count?: number | null;
};

function numOrNull(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function resolveCandidateSlotCoverage(input: SlotCoverageSemanticsInput): {
  used: number;
  capacity: number;
  label: string;
  tip: string;
} {
  const capacity =
    numOrNull(input.candidate_slot_capacity) ??
    numOrNull(input.max_positions) ??
    0;
  const usedDirect = numOrNull(input.candidate_slot_assigned);
  const usedFallback =
    (numOrNull(input.candidates_waiting) ?? 0) +
    (numOrNull(input.positions_open) ?? 0) +
    (numOrNull(input.pending_orders) ?? 0);
  const used = usedDirect ?? usedFallback;
  return {
    used,
    capacity,
    label: `${used} / ${capacity}`,
    tip:
      "자동매매 후보를 등록해 매수 조건을 감시하는 자리입니다. " +
      "적격 후보가 부족하면 빈 슬롯이 있을 수 있습니다.",
  };
}

export function resolveAutoPositionCoverage(input: SlotCoverageSemanticsInput): {
  used: number;
  limit: number;
  label: string;
  tip: string;
} {
  const limit =
    numOrNull(input.auto_position_limit) ??
    numOrNull(input.auto_slot_limit) ??
    0;
  const used =
    numOrNull(input.auto_position_used) ??
    numOrNull(input.auto_slot_used) ??
    0;
  return {
    used,
    limit,
    label: `${used} / ${limit}`,
    tip: "자동매매로 동시에 보유할 수 있는 최대 포지션 수입니다.",
  };
}

export function resolveDailyEntryCoverage(input: SlotCoverageSemanticsInput): {
  used: number;
  mode: string;
  limit: number | null;
  label: string;
  tip: string;
} {
  const de = input.daily_entry ?? {};
  const mode = String(
    input.daily_entry_limit_mode ?? de.mode ?? "LIMITED",
  )
    .trim()
    .toUpperCase();
  const used =
    numOrNull(input.daily_entry_used) ?? numOrNull(de.entry_count) ?? 0;
  const limit =
    numOrNull(input.daily_entry_limit) ?? numOrNull(de.entry_limit);
  const unlimited = mode === "UNLIMITED" || limit == null;
  return {
    used,
    mode,
    limit: unlimited ? null : limit,
    label: unlimited ? `${used} / 무제한` : `${used} / ${limit}`,
    tip: unlimited
      ? "오늘 AUTO 신규 진입 횟수입니다. 일일 한도는 무제한입니다."
      : "오늘 AUTO 신규 진입 횟수 / 일일 한도입니다.",
  };
}

export function resolveRealtimeMonitorCoverage(
  input: SlotCoverageSemanticsInput,
): {
  target: number | null;
  actual: number | null;
  label: string;
  tip: string;
} {
  const target = numOrNull(input.realtime_monitor_target);
  const actual = numOrNull(input.realtime_monitored_count);
  return {
    target,
    actual,
    label: target == null ? "—" : `${target}종목`,
    tip:
      "Scanner가 실시간 분석 대상으로 확보하려는 목표 종목 수입니다. " +
      "실제 후보 슬롯 수와 항상 같지는 않습니다.",
  };
}

export const EMPTY_SLOT_TOOLTIP_KO =
  "현재 등록할 적격 후보를 기다리고 있습니다.";

export const CANDIDATE_SLOT_TABLE_HINT_KO =
  "후보 슬롯은 항상 모두 채워지는 것이 아닙니다. " +
  "기술조건·AI 판단·기존 보유·재진입 제한 등을 통과한 적격 후보만 등록됩니다.";
