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

  it("formats duration with minutes and seconds", () => {
    const label = formatBlockDuration(
      "2026-09-05T06:07:06+09:00",
      "2026-09-05T07:30:06+09:00",
    );
    expect(label).toContain("시간");
  });

  it("exposes recovery lifecycle fields for resolved block", () => {
    const v = parseBlockHistoryView({
      kill_switch: { active: false },
      block_history: {
        status: "RESOLVED",
        blocked_at: "2026-09-05T06:07:06+09:00",
        unblocked_at: "2026-09-05T06:20:06+09:00",
        resolved_at: "2026-09-05T06:20:06+09:00",
        recovery_started_at: "2026-09-05T06:07:06+09:00",
        recovered_at: "2026-09-05T06:20:06+09:00",
        recovery_result: "SUCCESS",
        recovery_method: "AUTO",
        resolution_type: "AUTO_OBSERVED_CLEAR",
        primary_reason_code: "KILL_SWITCH_ACTIVE",
      },
    });
    expect(v.status).toBe("RESOLVED");
    expect(v.recoveryResult).toBe("SUCCESS");
    expect(v.recoveryMethod).toBe("AUTO");
    expect(v.recoveryStartedAt).toBeTruthy();
    expect(v.recoveredAt).toBeTruthy();
    expect(v.recoveryDurationLabel).toBeTruthy();
    expect(v.recoveryResultLabel).toBe("성공");
  });

  it("pending recovery while blocked", () => {
    const v = parseBlockHistoryView({
      kill_switch: { active: true },
      block_history: {
        status: "BLOCKED",
        blocked_at: "2026-09-05T06:07:06+09:00",
        recovery_result: "PENDING",
        primary_reason_code: "LIVE_OFF",
      },
    });
    expect(v.recoveryResult).toBe("PENDING");
    expect(v.recoveredAt).toBeNull();
    expect(v.recoveryResultLabel).toBe("진행 중");
  });
});
