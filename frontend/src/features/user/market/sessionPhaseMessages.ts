/**
 * STEP 8-5-13 — KRX Session Timeline Phase → 사용자 화면 한글 메시지.
 *
 * Backend `TradingSessionPhase` (operation/session_timeline.py) 와 동일한
 * 값 집합을 사용한다. `/user/market-calendar/status` 응답의 `phase` 필드,
 * Admin Timeline API의 `current_phase` 필드가 모두 이 값을 따른다.
 *
 * 시간 계산은 전부 Backend Timeline이 담당하므로, 이 모듈은 순수하게
 * "phase 문자열 → 한글 라벨/설명/색상" 매핑만 수행한다 (중복 시간 계산 없음).
 */

export type SessionPhase =
  | "PREOPEN"
  | "OPEN"
  | "EXIT_ONLY"
  | "CLOSED"
  | "POST_CLOSE"
  | "NON_TRADING_DAY"
  | "CALENDAR_UNAVAILABLE";

export type SessionPhaseTone = "info" | "success" | "warning" | "error";

export interface SessionPhaseMessage {
  /** Phase 값 (알 수 없는 값이 들어오면 원본 문자열 그대로 보존) */
  phase: string;
  /** 짧은 상태 라벨 (Tag 등에 사용) */
  label: string;
  /** 설명 문구 (Alert description 등에 사용) */
  description: string;
  /** Ant Design Alert/Tag에 매핑할 색상 계열 */
  tone: SessionPhaseTone;
}

const SESSION_PHASE_MESSAGES: Record<SessionPhase, SessionPhaseMessage> = {
  PREOPEN: {
    phase: "PREOPEN",
    label: "장전 준비 중",
    description: "정규장 개장 전입니다. 잠시 후 매매가 시작됩니다.",
    tone: "info",
  },
  OPEN: {
    phase: "OPEN",
    label: "정규장 운영 중",
    description: "신규 매수·매도 주문이 모두 가능합니다.",
    tone: "success",
  },
  EXIT_ONLY: {
    phase: "EXIT_ONLY",
    label: "신규 진입 마감",
    description: "신규 진입 마감 — 매도·위험 축소만 가능합니다.",
    tone: "warning",
  },
  CLOSED: {
    phase: "CLOSED",
    label: "장 마감",
    description: "정규장이 종료되었습니다.",
    tone: "info",
  },
  POST_CLOSE: {
    phase: "POST_CLOSE",
    label: "장 마감",
    description: "장 마감 이후 정산·복구 처리 중입니다.",
    tone: "info",
  },
  NON_TRADING_DAY: {
    phase: "NON_TRADING_DAY",
    label: "휴장일",
    description: "오늘은 휴장일입니다.",
    tone: "info",
  },
  CALENDAR_UNAVAILABLE: {
    phase: "CALENDAR_UNAVAILABLE",
    label: "거래일 정보 확인 불가",
    description:
      "거래일 정보를 확인할 수 없습니다. 잠시 후 다시 확인하거나 관리자에게 문의하세요.",
    tone: "error",
  },
};

const UNKNOWN_PHASE_MESSAGE: Omit<SessionPhaseMessage, "phase"> = {
  label: "상태 확인 중",
  description: "장 상태 정보를 불러오는 중입니다.",
  tone: "info",
};

/** phase 문자열(또는 null/undefined) → 한글 메시지. 알 수 없는 값은 안전한 기본값. */
export function getSessionPhaseMessage(
  phase: string | null | undefined,
): SessionPhaseMessage {
  if (!phase) {
    return { phase: "", ...UNKNOWN_PHASE_MESSAGE };
  }
  const known = SESSION_PHASE_MESSAGES[phase as SessionPhase];
  if (known) return known;
  return { phase, ...UNKNOWN_PHASE_MESSAGE };
}

export function formatSessionPhaseLabel(
  phase: string | null | undefined,
): string {
  return getSessionPhaseMessage(phase).label;
}

/** Ant Design Alert `type` prop과 호환되는 값으로 변환 */
export function sessionPhaseAlertType(
  phase: string | null | undefined,
): SessionPhaseTone {
  return getSessionPhaseMessage(phase).tone;
}

/** EXIT_ONLY/장마감 등 "신규 진입 불가" 여부 — 위험 축소(매도)는 별도 필드로 판단 */
export function isNewEntryBlockedPhase(
  phase: string | null | undefined,
): boolean {
  return phase !== "OPEN";
}
