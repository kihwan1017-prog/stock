import { describe, expect, it } from "vitest";

import {
  armDisplayLabel,
  getKiwoomLeaseDisplay,
  getKiwoomReadyDisplay,
  getRuntimeStackLabel,
  isArmOn,
  isLiveOn,
  liveDisplayLabel,
  resolveKiwoomReadyLabel,
} from "@/features/admin/autotrading/kiwoomAutotradingCanonicalStatus";

const OPS_HEALTHY = {
  live: "ON",
  arm: "ON",
  auto_trading_ready: true,
  auto_trading_state: "RUNNING",
  runtime_stack: { label: "4/4 RUNNING", running_count: 4, total: 4 },
  unattended: {
    status_code: "ACTIVE",
    entry_lease_active: true,
    authorization_mode: "MARKET_HOURS",
  },
};

describe("kiwoomAutotradingCanonicalStatus", () => {
  it('ops.live="ON" → LIVE "켜짐"', () => {
    expect(isLiveOn({ live: "ON" })).toBe("on");
    expect(liveDisplayLabel(isLiveOn({ live: "ON" }))).toBe("켜짐");
  });

  it('ops.live="OFF" → LIVE "꺼짐"', () => {
    expect(liveDisplayLabel(isLiveOn({ live: "OFF" }))).toBe("꺼짐");
  });

  it('ops.arm="ON" → ARM "승인"', () => {
    expect(armDisplayLabel(isArmOn({ arm: "ON" }))).toBe("승인");
  });

  it('ops.arm="OFF" → ARM "해제"', () => {
    expect(armDisplayLabel(isArmOn({ arm: "OFF" }))).toBe("해제");
  });

  it('runtime_stack.label="4/4 RUNNING" → STACK 정확 표시', () => {
    expect(getRuntimeStackLabel(OPS_HEALTHY)).toBe("4/4 RUNNING");
  });

  it("ready=true → 준비 완료", () => {
    expect(getKiwoomReadyDisplay(OPS_HEALTHY).label).toBe("준비 완료");
  });

  it("UPBIT readiness BLOCKED여도 Kiwoom ops ready=true면 차단됨 아님", () => {
    const upbitBlocked = {
      status: "BLOCKED",
      blockers: ["UBA_BROKER_MISMATCH", "STRATEGY_NOT_LIVE_APPROVED"],
    };
    expect(resolveKiwoomReadyLabel(OPS_HEALTHY, upbitBlocked)).toBe("준비 완료");
    expect(resolveKiwoomReadyLabel(OPS_HEALTHY, upbitBlocked)).not.toBe("차단됨");
  });

  it("MARKET_HOURS + lease ACTIVE → 장중 무인운영 활성", () => {
    expect(getKiwoomLeaseDisplay(OPS_HEALTHY)).toBe("장중 무인운영 활성");
  });

  it('24H mode일 때만 "24H 무인운영 활성"', () => {
    expect(
      getKiwoomLeaseDisplay({
        unattended: {
          status_code: "ACTIVE",
          entry_lease_active: true,
          authorization_mode: "HOURS_24",
        },
      }),
    ).toBe("24H 무인운영 활성");
  });

  it("unknown/null live field → 확인 불가 (false 오인 금지)", () => {
    expect(liveDisplayLabel(isLiveOn({}))).toBe("확인 불가");
    expect(liveDisplayLabel(isLiveOn({ live_on: true }))).toBe("확인 불가");
    expect(armDisplayLabel(isArmOn(null))).toBe("확인 불가");
  });

  it("stack label 없을 때 running_count/total fallback", () => {
    expect(
      getRuntimeStackLabel({
        runtime_stack: { running_count: 3, total: 4 },
      }),
    ).toBe("3/4");
  });

  it("stack 정보 없으면 확인 불가", () => {
    expect(getRuntimeStackLabel({})).toBe("확인 불가");
  });
});
