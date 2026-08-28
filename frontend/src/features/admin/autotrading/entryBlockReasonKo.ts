/**
 * Entry block reason → 한국어 설명 (화면마다 중복 구현 금지).
 * raw code는 tooltip/detail로만 노출. INTERNAL VALUE 불변.
 */

export const ENTRY_BLOCK_REASON_KO: Record<string, string> = {
  SHORT_MA_NOT_ABOVE_LONG_MA:
    "단기 이동평균이 장기 이동평균보다 낮거나 같습니다.",
  MA_SEPARATION_TOO_SMALL:
    "단기·장기 이동평균 차이가 충분하지 않습니다.",
  RSI_TOO_HIGH: "RSI가 매수 허용 범위보다 높습니다.",
  VOLUME_SURGE_TOO_LOW: "거래량 증가가 매수 기준에 미달합니다.",
  MISSING_VOLUME_SURGE: "거래량 급증 지표가 없습니다.",
  MISSING_RSI: "RSI 지표가 없습니다.",
  MISSING_MA: "이동평균 지표가 없습니다.",
  WARMING_UP: "매수 판단에 필요한 시세 데이터를 수집 중입니다.",
  FEED_STALE: "최근 시세 데이터가 신선하지 않습니다.",
  CANDIDATE_STALE: "후보 선정 데이터가 오래되었습니다.",
  NO_CANDIDATE_SNAPSHOT: "후보 스냅샷이 없습니다.",
  AI_HOLD: "AI가 현재 매수를 보류했습니다.",
  AI_HOLD_CURRENTLY: "AI가 현재 매수를 보류했습니다.",
  AI_SELECTION_NOT_ALLOW: "AI 판단이 매수 허용(ALLOW)이 아닙니다.",
  OWNERSHIP_BLOCK: "일반매매 또는 다른 자동매매가 관리 중인 종목입니다.",
  RISK_BLOCK: "리스크 정책에 의해 진입이 차단되었습니다.",
  ENTRY_EVALUATOR_STALE:
    "매수 조건 평가가 일정 시간 이상 갱신되지 않았습니다.",
  SIGNAL_EMIT_SUPPRESSED: "중복 매수 신호가 억제되었습니다.",
  MAX_OPEN_POSITIONS_REACHED:
    "계좌 전체 보유 종목 수 한도에 도달했습니다(수동 보유 포함).",
  PENDING_ENTRY_LIMIT: "대기 중 진입 주문 수 한도에 도달했습니다.",
  PORTFOLIO_PENDING_ENTRY_LIMIT:
    "포트폴리오 대기 진입 한도에 도달했습니다.",
  FULL_MARKET_NO_WAITING_SIGNAL_SLOT: "비어 있는 대기 슬롯이 없습니다.",
  SIGNALS_NOT_ALLOWED: "현재 신호 발생이 허용되지 않습니다.",
  PREV_MA_NOT_READY: "이전 이동평균이 아직 준비되지 않았습니다.",
  PORTFOLIO_ENTRY_CTX_MISSING: "포트폴리오 진입 컨텍스트가 없습니다.",
  ENTRY_POLICY_NOT_BULLISH_STATE: "상승 추세 진입 조건을 충족하지 않습니다.",
  MAX_ORDER_AMOUNT: "주문금액 한도를 초과합니다.",
  BELOW_MIN_NOTIONAL: "최소 주문금액에 미달합니다.",
  ARM_EXPIRED: "자동주문 승인(ARM)이 만료되었습니다.",
  LIVE_ARM_EXPIRED: "자동주문 승인(ARM)이 만료되었습니다.",
  UNKNOWN_OPEN_ORDER: "확인되지 않은 미체결 주문이 있습니다.",
};

/** 표·카드용 짧은 라벨 */
export const ENTRY_BLOCK_REASON_SHORT_KO: Record<string, string> = {
  SHORT_MA_NOT_ABOVE_LONG_MA: "단기 이동평균 조건 미충족",
  MA_SEPARATION_TOO_SMALL: "MA 간격 부족",
  RSI_TOO_HIGH: "RSI 과열",
  VOLUME_SURGE_TOO_LOW: "거래량 조건 미충족",
  MISSING_VOLUME_SURGE: "거래량 지표 없음",
  MISSING_RSI: "RSI 없음",
  MISSING_MA: "이동평균 없음",
  WARMING_UP: "초기 데이터 준비",
  FEED_STALE: "시세 데이터 지연",
  CANDIDATE_STALE: "후보 데이터 만료",
  NO_CANDIDATE_SNAPSHOT: "후보 없음",
  AI_HOLD: "AI 매수 대기",
  AI_HOLD_CURRENTLY: "AI 매수 대기",
  AI_SELECTION_NOT_ALLOW: "AI 매수 미허용",
  OWNERSHIP_BLOCK: "종목 소유권 차단",
  RISK_BLOCK: "리스크 차단",
  ENTRY_EVALUATOR_STALE: "평가 갱신 지연",
  SIGNAL_EMIT_SUPPRESSED: "중복 매수 신호 억제",
  MAX_OPEN_POSITIONS_REACHED: "계좌 보유 한도(수동 포함)",
  PENDING_ENTRY_LIMIT: "대기 진입 한도",
  PORTFOLIO_PENDING_ENTRY_LIMIT: "포트폴리오 대기 한도",
  FULL_MARKET_NO_WAITING_SIGNAL_SLOT: "대기 슬롯 없음",
  SIGNALS_NOT_ALLOWED: "신호 발생 미허용",
  PREV_MA_NOT_READY: "이동평균 미준비",
  PORTFOLIO_ENTRY_CTX_MISSING: "진입 컨텍스트 없음",
  ENTRY_POLICY_NOT_BULLISH_STATE: "상승 조건 미충족",
  MAX_ORDER_AMOUNT: "주문금액 한도 초과",
  BELOW_MIN_NOTIONAL: "최소 주문금액 미달",
  ARM_EXPIRED: "자동매매 승인 만료",
  LIVE_ARM_EXPIRED: "자동매매 승인 만료",
  UNKNOWN_OPEN_ORDER: "미확인 미체결 주문",
};

export function normalizeEntryBlockReasonCode(
  raw: string | null | undefined,
): string | null {
  if (raw == null) return null;
  const code = String(raw).trim().toUpperCase();
  if (!code || code === "NONE" || code === "NULL" || code === "-") {
    return null;
  }
  return code;
}

export function entryBlockReasonKo(
  raw: string | null | undefined,
): { label: string; detail: string; rawCode: string | null; known: boolean } {
  const code = normalizeEntryBlockReasonCode(raw);
  if (!code) {
    return { label: "—", detail: "", rawCode: null, known: true };
  }
  const detail = ENTRY_BLOCK_REASON_KO[code];
  const short = ENTRY_BLOCK_REASON_SHORT_KO[code];
  if (detail) {
    return {
      label: short ?? detail,
      detail,
      rawCode: code,
      known: true,
    };
  }
  // 알 수 없는 코드: 원본을 숨기지 않음
  const fallback = `확인 필요 (${code})`;
  return {
    label: fallback,
    detail: fallback,
    rawCode: code,
    known: false,
  };
}

export function entryBlockReasonShortKo(
  raw: string | null | undefined,
): string {
  return entryBlockReasonKo(raw).label;
}
