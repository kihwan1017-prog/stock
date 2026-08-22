/**
 * Entry block reason → 한국어 설명 (화면마다 중복 구현 금지).
 * raw code는 tooltip/detail로만 노출.
 */

export const ENTRY_BLOCK_REASON_KO: Record<string, string> = {
  SHORT_MA_NOT_ABOVE_LONG_MA:
    "단기 이동평균이 장기 이동평균보다 낮거나 같습니다.",
  MA_SEPARATION_TOO_SMALL:
    "단기·장기 이동평균 차이가 충분하지 않습니다.",
  RSI_TOO_HIGH: "RSI가 매수 허용 범위보다 높습니다.",
  VOLUME_SURGE_TOO_LOW: "거래량 증가가 매수 기준에 미달합니다.",
  WARMING_UP: "매수 판단에 필요한 시세 데이터를 수집 중입니다.",
  FEED_STALE: "최근 시세 데이터가 신선하지 않습니다.",
  CANDIDATE_STALE: "후보 선정 데이터가 오래되었습니다.",
  AI_HOLD: "AI가 현재 매수를 보류했습니다.",
  OWNERSHIP_BLOCK: "일반매매 또는 다른 자동매매가 관리 중인 종목입니다.",
  RISK_BLOCK: "리스크 정책에 의해 진입이 차단되었습니다.",
  ENTRY_EVALUATOR_STALE:
    "매수 조건 평가가 일정 시간 이상 갱신되지 않았습니다.",
};

/** 표·카드용 짧은 라벨 */
export const ENTRY_BLOCK_REASON_SHORT_KO: Record<string, string> = {
  SHORT_MA_NOT_ABOVE_LONG_MA: "단기 이동평균 조건 미충족",
  MA_SEPARATION_TOO_SMALL: "MA 간격 부족",
  RSI_TOO_HIGH: "RSI 높음",
  VOLUME_SURGE_TOO_LOW: "거래량 증가 미달",
  WARMING_UP: "Warm-up",
  FEED_STALE: "시세 데이터 지연",
  CANDIDATE_STALE: "후보 데이터 만료",
  AI_HOLD: "AI 매수 보류",
  OWNERSHIP_BLOCK: "종목 소유권 차단",
  RISK_BLOCK: "리스크 차단",
  ENTRY_EVALUATOR_STALE: "평가 갱신 지연",
};

const UNKNOWN_KO = "현재 차단 사유를 확인할 수 없습니다.";

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
  return {
    label: UNKNOWN_KO,
    detail: UNKNOWN_KO,
    rawCode: code,
    known: false,
  };
}

export function entryBlockReasonShortKo(
  raw: string | null | undefined,
): string {
  return entryBlockReasonKo(raw).label;
}
