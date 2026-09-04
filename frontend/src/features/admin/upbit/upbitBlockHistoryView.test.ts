import { describe, expect, it } from "vitest";

import {
  formatBlockDuration,
  parseBlockHistoryView,
} from "./upbitBlockHistoryView";

describe("upbitBlockHistoryView", () => {
  it("renders blocked provenance from kill + block_history", () => {
    const v = parseBlockHistoryView({
      primary_blocker: "LIVE_OFF",
      blockers: ["LIVE_OFF", "ARM_OFF"],
      kill_switch: {
        active: true,
        scope_code: "UBA:1380",
        reason: "POSITION_MISMATCH",
        activated_at: "2026-09-05T06:07:06+09:00",
      },
      block_history: {
        status: "BLOCKED",
        blocked_at: "2026-09-05T06:07:06+09:00",
        primary_reason_code: "KILL_SWITCH_ACTIVE",
        primary_reason_text:
          "체결 후 포지션 검증에서 불일치가 감지되어 안전장치가 동작했습니다.",
        secondary_reasons: ["LIVE_OFF", "ARM_OFF"],
        kill_switch_scope: "UBA:1380",
        kill_switch_reason: "POSITION_MISMATCH",
      },
    });
    expect(v.status).toBe("BLOCKED");
    expect(v.primaryCode).toBe("KILL_SWITCH_ACTIVE");
    expect(v.primaryText).toContain("포지션");
    expect(v.killScope).toBe("UBA:1380");
    expect(v.blockedAt).toBeTruthy();
    expect(v.durationLabel).toBeTruthy();
  });

  it("READY + NO_CANDIDATES is not forced BLOCKED without kill", () => {
    const v = parseBlockHistoryView({
      primary_blocker: null,
      blockers: [],
      kill_switch: { active: false },
      block_history: { status: "NONE" },
    });
    expect(v.status).toBe("NONE");
  });

  it("formats duration", () => {
    const label = formatBlockDuration(
      "2026-09-05T06:07:06+09:00",
      "2026-09-05T07:30:06+09:00",
    );
    expect(label).toContain("시간");
  });
});
