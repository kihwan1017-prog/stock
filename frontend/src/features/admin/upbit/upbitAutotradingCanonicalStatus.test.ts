import { describe, expect, it } from "vitest";

import {
  buildUpbitAutotradingAggregateStatus,
  mergeAutotradingBlockers,
  parseOpsLiveArm,
} from "@/features/admin/upbit/upbitAutotradingCanonicalStatus";

describe("upbitAutotradingCanonicalStatus", () => {
  it("parseOpsLiveArm — ops-status `live`/`arm` 문자열 SoT", () => {
    expect(parseOpsLiveArm({ live: "ON", arm: "ON" }).liveOn).toBe(true);
    expect(parseOpsLiveArm({ live: "ON", arm: "ON" }).armOn).toBe(true);
    expect(parseOpsLiveArm({ live: "OFF", arm: "OFF" }).liveOn).toBe(false);
    expect(parseOpsLiveArm({ live: "OFF", arm: "OFF" }).armOn).toBe(false);
    // 잘못된 레거시 필드만 있으면 OFF (live_on 미사용)
    expect(
      parseOpsLiveArm({ live_on: true, live_order_enabled: true }).liveOn,
    ).toBe(false);
  });

  it("ENTRY_RESTRICTED — 청산 체결 대기 (SYSTEM_BLOCKED 아님)", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: {
        live: "ON",
        arm: "ON",
        blockers: [],
        operational_semantics: {
          operational_tier: "ENTRY_RESTRICTED",
          entry_restricted: true,
          system_blocked: false,
          primary_blocker_ko: "청산 주문 체결 대기",
        },
        reliability: {
          health_state: "READY",
          health_reasons: ["EXIT_PENDING_ZERO_FILL_STUCK"],
          auto_trading_ready: true,
        },
      },
      readiness: { status: "READY_FOR_AUTO_TRADING", blockers: [] },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.tier).toBe("entry_restricted");
    expect(agg.headline).toBe("청산 주문 체결 대기");
    expect(agg.headline).not.toBe("자동매매 차단");
    expect(agg.entryOrdersPermitted).toBe(false);
    expect(agg.systemBlocked).toBe(false);
  });

  it("FIRST_ZERO informational — 차단 headline 금지", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: {
        live: "ON",
        arm: "ON",
        operational_semantics: {
          operational_tier: "RUNNING",
          informational_first_zero: true,
        },
        reliability: {
          health_state: "READY",
          first_zero_stage: "CANDIDATE",
          first_zero_reason: "NO_CANDIDATE_SNAPSHOT",
          auto_trading_ready: true,
        },
      },
      readiness: { status: "READY_FOR_AUTO_TRADING", blockers: [] },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.headline).not.toBe("자동매매 차단");
    expect(agg.tier).toBe("available_waiting");
  });

  it("ARM OFF → SYSTEM_BLOCKED 자동매매 차단", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: { live: "OFF", arm: "OFF", blockers: ["LIVE_OFF", "ARM_OFF"] },
      readiness: {
        status: "READY_FOR_AUTO_TRADING",
        blockers: [],
      },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.tier).toBe("system_blocked");
    expect(agg.headline).toBe("자동매매 차단");
    expect(agg.entryOrdersPermitted).toBe(false);
    expect(agg.blockers).toContain("LIVE_OFF");
  });

  it("LIVE ON + ARM ON + readiness READY + evaluator RUNNING → 가능·대기", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: {
        live: "ON",
        arm: "ON",
        auto_trading_state: "RUNNING",
        blockers: [],
      },
      readiness: {
        status: "READY_FOR_AUTO_TRADING",
        blockers: [],
      },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.tier).toBe("available_waiting");
    expect(agg.headline).toBe("자동매매 가능 · 매수조건 대기");
    expect(agg.entryOrdersPermitted).toBe(true);
  });

  it("evaluator RUNNING이어도 LIVE OFF면 entryOrdersPermitted=false", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: { live: "OFF", arm: "ON" },
      readiness: { status: "READY_FOR_AUTO_TRADING" },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.entryOrdersPermitted).toBe(false);
  });

  it("mergeAutotradingBlockers — ops LIVE/ARM 우선", () => {
    expect(
      mergeAutotradingBlockers(
        { live: "OFF", arm: "OFF" },
        { blockers: [] },
      ),
    ).toEqual(expect.arrayContaining(["LIVE_OFF", "ARM_OFF_OR_EXPIRED"]));
  });

  it("partial_restore=true → PARTIAL_RESTORE 문구", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: {
        live: "ON",
        arm: "ON",
        blockers: [],
        reliability: {
          health_state: "BROKEN",
          partial_restore: true,
          health_reasons: ["STACK_INCOMPLETE"],
          first_zero_stage: "ENTRY_SIGNAL",
        },
      },
      readiness: { status: "READY_FOR_AUTO_TRADING", blockers: [] },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.description).toContain("실행 스택 불완전 (PARTIAL_RESTORE)");
    expect(agg.description).toContain("Funnel FIRST_ZERO=ENTRY_SIGNAL");
    expect(agg.description).not.toContain("대기 슬롯 포화");
    expect(agg.entryOrdersPermitted).toBe(false);
  });

  it("WAITING_SLOT_STARVATION_BROKEN → 슬롯 포화 문구 (PARTIAL_RESTORE 금지)", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: {
        live: "ON",
        arm: "ON",
        blockers: [],
        reliability: {
          health_state: "BROKEN",
          partial_restore: false,
          health_reasons: ["WAITING_SLOT_STARVATION_BROKEN"],
          no_trade_classification: "WAITING_SLOT_STARVATION",
          waiting_starvation: {
            waiting_slot_starvation: true,
            waiting_count: 10,
            oldest_waiting_age_seconds: 13793,
          },
          waiting_count: 10,
          first_zero_stage: "ENTRY_SIGNAL",
          first_zero_reason: "SHORT_MA_NOT_ABOVE_LONG_MA",
        },
      },
      readiness: { status: "READY_FOR_AUTO_TRADING", blockers: [] },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.headline).toContain("자동매매 후보 대기 슬롯 포화");
    expect(agg.description).toContain(
      "대기 후보가 기술조건 미충족 상태로 장시간 슬롯을 점유",
    );
    expect(agg.description).toContain("실행 프로세스는 정상");
    expect(agg.description).toContain("Funnel FIRST_ZERO=ENTRY_SIGNAL");
    expect(agg.description).not.toContain("실행 스택 불완전 (PARTIAL_RESTORE)");
    expect(agg.description).not.toMatch(/runtime failure/i);
    expect(agg.entryOrdersPermitted).toBe(false);
  });

  it("stack 정상 + health BROKEN(기타) → PARTIAL_RESTORE/runtime failure 문구 금지", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: {
        live: "ON",
        arm: "ON",
        blockers: [],
        reliability: {
          health_state: "BROKEN",
          partial_restore: false,
          health_reasons: ["SOME_OTHER_BROKEN"],
          first_zero_stage: "ENTRY_SIGNAL",
        },
      },
      readiness: { status: "READY_FOR_AUTO_TRADING", blockers: [] },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.description).not.toContain("실행 스택 불완전 (PARTIAL_RESTORE)");
    expect(agg.description).not.toMatch(/runtime failure/i);
    expect(agg.description).toContain("운영 상태 이상");
    expect(agg.description).toContain("SOME_OTHER_BROKEN");
  });
});
