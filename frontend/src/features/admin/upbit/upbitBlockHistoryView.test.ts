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
        recovery_status: "AWAITING_OPERATOR",
        recovery_method: "NOT_ATTEMPTED",
      },
    });
    expect(v.status).toBe("BLOCKED");
    expect(v.primaryCode).toBe("KILL_SWITCH_ACTIVE");
    expect(v.primaryText).toContain("포지션");
    expect(v.killScope).toBe("UBA:1380");
    expect(v.blockedAt).toBeTruthy();
    expect(v.durationLabel).toBeTruthy();
    expect(v.recoveryScheduledAt).toBeNull();
    expect(v.recoveryAttemptedAt).toBeNull();
    expect(v.recoveryStatus).toBe("AWAITING_OPERATOR");
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

  it("does not treat blocked_at alias as recovery attempt", () => {
    const v = parseBlockHistoryView({
      kill_switch: { active: false },
      block_history: {
        status: "BLOCKED",
        blocked_at: "2026-09-06T00:09:56+09:00",
        // H129 legacy: recovery_started_at == blocked_at 는 시도로 보지 않음
        recovery_started_at: "2026-09-06T00:09:56+09:00",
        recovery_method: "NOT_ATTEMPTED",
      },
    });
    expect(v.recoveryAttemptedAt).toBeNull();
    expect(v.recoveryScheduledAt).toBeNull();
    expect(v.recoveryStatusLabel).toContain("운영자");
  });

  it("shows scheduled timestamp only when canonical field exists", () => {
    const v = parseBlockHistoryView({
      kill_switch: { active: false },
      block_history: {
        status: "BLOCKED",
        blocked_at: "2026-09-06T00:09:56+09:00",
        recovery_scheduled_at: "2026-09-06T01:00:00+09:00",
        recovery_status: "SCHEDULED",
      },
    });
    expect(v.recoveryScheduledAt).toBeTruthy();
    expect(v.recoveryStatus).toBe("SCHEDULED");
    expect(v.recoveryStatusLabel).toBe("대기 중");
  });

  it("exposes recovery lifecycle fields for resolved block", () => {
    const v = parseBlockHistoryView({
      kill_switch: { active: false },
      block_history: {
        status: "RESOLVED",
        blocked_at: "2026-09-05T06:07:06+09:00",
        unblocked_at: "2026-09-05T06:20:06+09:00",
        resolved_at: "2026-09-05T06:20:06+09:00",
        recovery_attempted_at: "2026-09-05T06:15:00+09:00",
        recovered_at: "2026-09-05T06:20:06+09:00",
        recovery_result: "SUCCESS",
        recovery_status: "SUCCESS",
        recovery_method: "OPERATOR_APPROVED",
        resolution_type: "OPERATOR_APPROVED",
        primary_reason_code: "LIVE_OFF",
      },
    });
    expect(v.status).toBe("RESOLVED");
    expect(v.recoveryStatus).toBe("SUCCESS");
    expect(v.recoveryMethod).toBe("OPERATOR_APPROVED");
    expect(v.recoveryMethodLabel).toContain("운영자");
    expect(v.recoveryAttemptedAt).toBeTruthy();
    expect(v.recoveredAt).toBeTruthy();
    expect(v.recoveryDurationLabel).toBeTruthy();
  });
});
