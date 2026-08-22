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

  it("A–F: LIVE/ARM OFF + readiness READY → 차단", () => {
    const agg = buildUpbitAutotradingAggregateStatus({
      ops: { live: "OFF", arm: "OFF", blockers: ["LIVE_OFF", "ARM_OFF"] },
      readiness: {
        status: "READY_FOR_AUTO_TRADING",
        blockers: [],
      },
      entryEvaluatorState: "RUNNING",
    });
    expect(agg.tier).toBe("blocked");
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
});
