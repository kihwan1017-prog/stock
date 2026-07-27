import { describe, expect, it } from "vitest";

import {
  formatSessionPhaseLabel,
  getSessionPhaseMessage,
  isNewEntryBlockedPhase,
  sessionPhaseAlertType,
} from "./sessionPhaseMessages";

describe("sessionPhaseMessages", () => {
  it("알려진 phase 값 각각에 대해 한글 라벨/설명/색상을 반환한다", () => {
    const preopen = getSessionPhaseMessage("PREOPEN");
    expect(preopen.label).toBe("장전 준비 중");
    expect(preopen.tone).toBe("info");

    const open = getSessionPhaseMessage("OPEN");
    expect(open.label).toBe("정규장 운영 중");
    expect(open.tone).toBe("success");

    const exitOnly = getSessionPhaseMessage("EXIT_ONLY");
    expect(exitOnly.label).toBe("신규 진입 마감");
    expect(exitOnly.tone).toBe("warning");

    const closed = getSessionPhaseMessage("CLOSED");
    expect(closed.label).toBe("장 마감");

    const postClose = getSessionPhaseMessage("POST_CLOSE");
    expect(postClose.description).toContain("정산·복구");

    const nonTradingDay = getSessionPhaseMessage("NON_TRADING_DAY");
    expect(nonTradingDay.description).toBe("오늘은 휴장일입니다.");

    const calendarUnavailable = getSessionPhaseMessage("CALENDAR_UNAVAILABLE");
    expect(calendarUnavailable.tone).toBe("error");
  });

  it("알 수 없는 phase 값은 원본 문자열을 보존하며 안전한 기본값을 반환한다", () => {
    const unknown = getSessionPhaseMessage("SOMETHING_NEW");
    expect(unknown.phase).toBe("SOMETHING_NEW");
    expect(unknown.label).toBe("상태 확인 중");
    expect(unknown.tone).toBe("info");
  });

  it("null/undefined phase는 빈 phase와 기본 메시지를 반환한다", () => {
    expect(getSessionPhaseMessage(null).phase).toBe("");
    expect(getSessionPhaseMessage(undefined).label).toBe("상태 확인 중");
  });

  it("formatSessionPhaseLabel은 label만 추출한다", () => {
    expect(formatSessionPhaseLabel("OPEN")).toBe("정규장 운영 중");
    expect(formatSessionPhaseLabel(null)).toBe("상태 확인 중");
  });

  it("sessionPhaseAlertType은 Ant Design Alert type과 호환되는 값을 반환한다", () => {
    expect(sessionPhaseAlertType("OPEN")).toBe("success");
    expect(sessionPhaseAlertType("EXIT_ONLY")).toBe("warning");
    expect(sessionPhaseAlertType("CALENDAR_UNAVAILABLE")).toBe("error");
  });

  it("isNewEntryBlockedPhase은 OPEN일 때만 false다", () => {
    expect(isNewEntryBlockedPhase("OPEN")).toBe(false);
    expect(isNewEntryBlockedPhase("EXIT_ONLY")).toBe(true);
    expect(isNewEntryBlockedPhase("CLOSED")).toBe(true);
    expect(isNewEntryBlockedPhase(null)).toBe(true);
  });
});
