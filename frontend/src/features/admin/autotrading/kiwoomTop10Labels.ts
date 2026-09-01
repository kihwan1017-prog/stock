/**
 * Kiwoom TOP10 REAL — 사용자용 한글 라벨 (raw enum 노출 금지).
 */

const CROSS_STATE_KO: Record<string, string> = {
  FRESH_CROSS: "Fresh Cross 감지",
  ABOVE_NO_NEW_CROSS: "골든크로스 대기(이미 상회)",
  BELOW: "골든크로스 대기",
  INSUFFICIENT_HISTORY: "이력 부족",
  UNKNOWN: "확인 중",
};

const SIGNAL_STATUS_KO: Record<string, string> = {
  SHADOW_CANDIDATE: "Shadow 후보",
  REAL_CANDIDATE: "REAL 매수조건 감시 중",
  REAL_DISPATCHED: "주문 경로 전달",
  REAL_PUBLISHED: "신호 발행",
  NONE: "감시 중",
  BLOCKED: "차단",
  ORDER_SUBMITTED: "주문 제출",
  FILLED: "체결",
};

const BLOCK_REASON_KO: Record<string, string> = {
  NO_FRESH_GOLDEN_CROSS: "Fresh Golden Cross 미발생",
  ABOVE_NO_NEW_CROSS: "이미 감지한 Cross(신규 이벤트 없음)",
  INSUFFICIENT_HISTORY: "일봉 이력 부족",
  ALREADY_POSITIONED: "이미 보유 중",
  RISK_GATE: "Risk Gate 차단",
  AI_GATE: "AI Gate 차단",
  LIVE_OFF: "LIVE 비활성",
  ARM_OFF: "ARM 비활성",
  FEED_STALE: "시세(Feed) 지연",
  ORDER_IN_FLIGHT: "주문 진행 중",
  DUPLICATE_REAL_SIGNAL: "중복 REAL 신호 차단",
  SHADOW_ONLY: "Shadow 관측만(REAL 미승격)",
};

export function kiwoomCrossStateLabelKo(raw: unknown): string {
  const key = String(raw ?? "").trim().toUpperCase();
  if (!key) return "—";
  return CROSS_STATE_KO[key] ?? "상태 확인 중";
}

export function kiwoomFreshCrossLabelKo(crossState: unknown): string {
  const key = String(crossState ?? "").trim().toUpperCase();
  return key === "FRESH_CROSS" ? "감지" : "대기";
}

export function kiwoomSignalStatusLabelKo(raw: unknown): string {
  const key = String(raw ?? "").trim().toUpperCase();
  if (!key) return "감시 중";
  return SIGNAL_STATUS_KO[key] ?? "감시 중";
}

export function kiwoomWhyNoTradeLabelKo(raw: unknown): string {
  const key = String(raw ?? "").trim().toUpperCase();
  if (!key) return "—";
  return BLOCK_REASON_KO[key] ?? "기타 차단 요인";
}

export function kiwoomModeTitleKo(mode: unknown, realEnabled: boolean): string {
  const m = String(mode ?? "").trim().toUpperCase();
  if (m === "REAL" || realEnabled) return "TOP10 REAL 자동매매";
  return "TOP10 SHADOW 관측";
}
