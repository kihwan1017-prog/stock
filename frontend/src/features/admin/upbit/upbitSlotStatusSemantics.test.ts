import { describe, expect, it } from "vitest";

import { slotStatusLabelKo } from "@/features/admin/autotrading/slotStatusLabels";
import {
  resolveAutoPositionCoverage,
  resolveCandidateSlotCoverage,
  resolveDailyEntryCoverage,
  resolveRealtimeMonitorCoverage,
} from "@/features/admin/upbit/upbitSlotStatusSemantics";
import { UI_LABEL_KO } from "@/features/shared/display/displayUiLabelsKo";

describe("upbitSlotStatusSemantics", () => {
  it("candidate capacity 10 / assigned 5 → 5 / 10", () => {
    const c = resolveCandidateSlotCoverage({
      candidate_slot_assigned: 5,
      candidate_slot_capacity: 10,
      auto_position_limit: 6,
      auto_slot_limit: 6,
    });
    expect(c.label).toBe("5 / 10");
    expect(c.capacity).toBe(10);
    expect(c.used).toBe(5);
  });

  it("AUTO position 2/6 does not use candidate capacity", () => {
    const a = resolveAutoPositionCoverage({
      auto_position_used: 2,
      auto_position_limit: 6,
      candidate_slot_capacity: 10,
      candidate_slot_assigned: 5,
    });
    expect(a.label).toBe("2 / 6");
    expect(a.limit).toBe(6);
    expect(a.used).toBe(2);
  });

  it("daily UNLIMITED → 5 / 무제한", () => {
    const d = resolveDailyEntryCoverage({
      daily_entry_used: 5,
      daily_entry_limit_mode: "UNLIMITED",
      daily_entry_limit: null,
    });
    expect(d.label).toBe("5 / 무제한");
    expect(d.mode).toBe("UNLIMITED");
  });

  it("daily LIMITED 10 / used 5 → 5 / 10", () => {
    const d = resolveDailyEntryCoverage({
      daily_entry_used: 5,
      daily_entry_limit_mode: "LIMITED",
      daily_entry_limit: 10,
    });
    expect(d.label).toBe("5 / 10");
  });

  it("realtime target 10 → 10종목", () => {
    const r = resolveRealtimeMonitorCoverage({
      realtime_monitor_target: 10,
      realtime_monitored_count: 8,
    });
    expect(r.label).toBe("10종목");
    expect(r.target).toBe(10);
  });

  it("EMPTY slot user label is 후보 대기", () => {
    expect(slotStatusLabelKo("EMPTY")).toBe("후보 대기");
  });

  it("candidate 10 and position 6 are not swapped", () => {
    const cand = resolveCandidateSlotCoverage({
      candidate_slot_assigned: 5,
      candidate_slot_capacity: 10,
      auto_slot_limit: 6,
    });
    const pos = resolveAutoPositionCoverage({
      auto_position_used: 2,
      auto_slot_limit: 6,
      candidate_slot_capacity: 10,
    });
    expect(cand.capacity).toBe(10);
    expect(pos.limit).toBe(6);
    expect(cand.label).not.toBe(pos.label);
  });

  it("null / loading safe", () => {
    expect(resolveCandidateSlotCoverage({}).label).toBe("0 / 0");
    expect(resolveAutoPositionCoverage({}).label).toBe("0 / 0");
    expect(resolveRealtimeMonitorCoverage({}).label).toBe("—");
    expect(resolveDailyEntryCoverage({}).label).toMatch(/무제한|0 \/ 0/);
  });

  it("UI labels distinguish concepts", () => {
    expect(UI_LABEL_KO.candidateWatchSlots).toContain("후보");
    expect(UI_LABEL_KO.autoHoldPositions).toContain("AUTO");
    expect(UI_LABEL_KO.autoHoldPositions).toContain("포지션");
    expect(UI_LABEL_KO.portfolioSlots).toContain("감시");
    expect(UI_LABEL_KO.blockReason).toBe("대기 이유");
  });
});
