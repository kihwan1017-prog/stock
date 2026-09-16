import { describe, expect, it } from "vitest";

import { AdminAccountLiveControlPanel } from "./AdminAccountLiveControlPanel";
import { ArmTokenOnceModal } from "./ArmTokenOnceModal";
import {
  armReissueGuidance,
  formatArmCountdown,
  maskArmToken,
  parseArmOnSuccessPayload,
} from "./armTokenOnceReveal";

describe("armTokenOnceReveal helpers", () => {
  it("parses fresh ARM ON payload with arm_token and expires_at", () => {
    const out = parseArmOnSuccessPayload(
      {
        already_armed: false,
        arm_token: "plain-token-once-only",
        arm_expires_at: "2026-08-04T13:05:00.000Z",
      },
      42,
    );
    expect(out).toEqual({
      ubaId: 42,
      armToken: "plain-token-once-only",
      expiresAt: "2026-08-04T13:05:00.000Z",
    });
  });

  it("accepts expires_at alias when arm_expires_at missing", () => {
    const out = parseArmOnSuccessPayload(
      {
        arm_token: "tok",
        expires_at: "2026-08-04T13:05:00.000Z",
      },
      7,
    );
    expect(out?.expiresAt).toBe("2026-08-04T13:05:00.000Z");
  });

  it("does not re-show token when already_armed", () => {
    expect(
      parseArmOnSuccessPayload(
        {
          already_armed: true,
          arm_token: "should-not-use",
          arm_expires_at: "2026-08-04T13:05:00.000Z",
        },
        1,
      ),
    ).toBeNull();
  });

  it("returns null when arm_token missing", () => {
    expect(
      parseArmOnSuccessPayload(
        {
          already_armed: false,
          arm_expires_at: "2026-08-04T13:05:00.000Z",
        },
        1,
      ),
    ).toBeNull();
  });

  it("masks token until revealed", () => {
    const token = "abcdefghijklmnop";
    const masked = maskArmToken(token, false);
    expect(masked).not.toBe(token);
    expect(masked.startsWith("abcd")).toBe(true);
    expect(masked.endsWith("mnop")).toBe(true);
    expect(masked.includes("•")).toBe(true);
    expect(maskArmToken(token, true)).toBe(token);
  });

  it("formats countdown and expired state", () => {
    const now = Date.parse("2026-08-04T13:00:00.000Z");
    const live = formatArmCountdown("2026-08-04T13:02:05.000Z", now);
    expect(live.expired).toBe(false);
    expect(live.remainingSeconds).toBe(125);
    expect(live.label).toContain("02:05");

    const done = formatArmCountdown("2026-08-04T12:59:00.000Z", now);
    expect(done.expired).toBe(true);
    expect(done.label).toBe("만료됨");
  });

  it("guides DISARM→ARM only when scheduler is paused", () => {
    const paused = armReissueGuidance(true);
    expect(paused).toContain("DISARM");
    expect(paused).toContain("ARM");
    expect(paused).toContain("PAUSE");

    const running = armReissueGuidance(false);
    expect(running).toContain("PAUSE");
    expect(running).toContain("DISARM");
    expect(running).not.toBe(paused);
  });
});

describe("ArmTokenOnceModal / AdminAccountLiveControlPanel surface", () => {
  it("exports modal and panel modules", () => {
    expect(typeof ArmTokenOnceModal).toBe("function");
    expect(typeof AdminAccountLiveControlPanel).toBe("function");
  });
});
