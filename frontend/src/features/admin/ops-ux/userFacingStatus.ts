/**
 * 기술 상태 코드 → 운영자용 한글 표현.
 * raw canonical 값은 상세/고급에서 그대로 확인 가능해야 한다.
 */

export type UserFacingStatus = {
  label: string;
  tone: "success" | "warning" | "error" | "default" | "processing";
  raw: string;
};

const SLOT_STATUS_MAP: Record<string, { label: string; tone: UserFacingStatus["tone"] }> = {
  OPEN: { label: "보유 중", tone: "success" },
  WAITING_SIGNAL: { label: "매수조건 감시 중", tone: "processing" },
  ENTRY_PENDING: { label: "매수 진행 중", tone: "processing" },
  EMPTY: { label: "후보 대기", tone: "default" },
  EXIT_PENDING: { label: "매도 주문 처리 중", tone: "warning" },
  BLOCKED: { label: "일시 차단", tone: "error" },
  SELECTED: { label: "후보 선정됨", tone: "processing" },
  COOLDOWN: { label: "재진입 대기", tone: "default" },
  REENTRY_WAIT: { label: "재진입 대기", tone: "default" },
  ERROR: { label: "오류", tone: "error" },
};

const WHY_NO_TRADE_MAP: Record<string, string> = {
  SIGNAL_EMIT_SUPPRESSED: "중복 신호 대기 중",
  SHORT_MA_NOT_ABOVE_LONG_MA: "매수 조건(추세) 미충족",
  ENTRY_SIGNAL_WAIT: "매수 신호 대기 중",
  PORTFOLIO_PENDING_ENTRY_LIMIT: "동시 주문 한도 대기",
  MAX_OPEN_POSITIONS_REACHED: "최대 보유 종목 수 도달",
  FULL_MARKET_NO_WAITING_SIGNAL_SLOT: "대기 슬롯 없음",
  Order_amount_exceeds_configured_limit: "주문 한도 때문에 대기",
  "Order amount exceeds configured limit": "주문 한도 때문에 대기",
  PIPELINE_STALL: "처리 지연 — 확인 필요",
  FEED_DOWN: "시세 연결 문제",
  STACK_DOWN: "실행 엔진 문제",
  NORMAL_NO_SIGNAL: "정상 — 매수 조건 대기",
};

export function formatSlotStatus(raw: unknown): UserFacingStatus {
  const code = String(raw ?? "").trim().toUpperCase();
  const mapped = SLOT_STATUS_MAP[code];
  if (mapped) return { ...mapped, raw: code || "—" };
  return {
    label: code || "알 수 없음",
    tone: "default",
    raw: code || "—",
  };
}

export function formatWhyNoTradeReason(raw: unknown): string {
  const text = String(raw ?? "").trim();
  if (!text) return "사유 없음";
  if (WHY_NO_TRADE_MAP[text]) return WHY_NO_TRADE_MAP[text];
  const upper = text.toUpperCase();
  for (const [key, label] of Object.entries(WHY_NO_TRADE_MAP)) {
    if (upper.includes(key.toUpperCase()) || text.includes(key)) return label;
  }
  if (text.includes("amount exceeds")) return "주문 한도 때문에 대기";
  if (text.includes("quantity exceeds")) return "수량 한도 때문에 대기";
  return text;
}

export function formatOverallHealth(raw: unknown): UserFacingStatus {
  const code = String(raw ?? "").trim().toUpperCase();
  if (code === "GREEN") return { label: "자동매매 정상", tone: "success", raw: code };
  if (code === "YELLOW") return { label: "정상 대기", tone: "warning", raw: code };
  if (code === "ORANGE") return { label: "확인 필요", tone: "warning", raw: code };
  if (code === "RED") return { label: "조치 필요", tone: "error", raw: code };
  return { label: code || "상태 확인 중", tone: "default", raw: code || "—" };
}

export function formatLiveArm(live: unknown, arm: unknown): string {
  const liveOn = String(live ?? "").toUpperCase() === "ON";
  const armOn = String(arm ?? "").toUpperCase() === "ON";
  if (liveOn && armOn) return "자동매매 실행 가능";
  if (liveOn && !armOn) return "LIVE만 켜짐 — ARM 필요";
  if (!liveOn && armOn) return "ARM만 켜짐 — LIVE 필요";
  return "자동매매 중지";
}
