/**
 * 운영/주문/판단 enum → 화면 한글 (INTERNAL VALUE 불변).
 */

export function decisionLabelKo(raw: string | null | undefined): string {
  const s = String(raw ?? "").trim().toUpperCase();
  switch (s) {
    case "ALLOW":
      return "매수 허용";
    case "HOLD":
      return "대기";
    case "REDUCE":
      return "비중 축소";
    case "BLOCK":
      return "차단";
    case "EMIT":
      return "신호 발생";
    case "TECHNICAL_PASS":
      return "기술조건 통과";
    case "CONFIRMING":
      return "확인 중";
    case "RESET":
      return "초기화";
    case "—":
    case "":
    case "-":
      return "—";
    default:
      return s ? `확인 필요 (${s})` : "—";
  }
}

export function runtimeValueLabelKo(raw: string | null | undefined): string {
  const s = String(raw ?? "").trim().toUpperCase();
  switch (s) {
    case "RUNNING":
      return "실행 중";
    case "STOPPED":
      return "중지";
    case "PAUSED":
      return "일시정지";
    case "ACTIVE":
      return "활성";
    case "INACTIVE":
      return "비활성";
    case "ON":
      return "켜짐";
    case "OFF":
      return "꺼짐";
    case "READY":
    case "READY_FOR_AUTO_TRADING":
      return "자동매매 준비 완료";
    case "BLOCKED":
      return "차단됨";
    case "DEGRADED":
      return "일부 장애";
    case "WARNING":
      return "주의";
    case "REAL_FRESH":
      return "실시간 시세 정상";
    case "STALE":
    case "FEED_STALE":
      return "시세 지연";
    case "WARMING_UP":
      return "초기 데이터 준비";
    case "—":
    case "-":
    case "":
      return "—";
    default:
      return s ? s : "—";
  }
}

export function orderStatusLabelKo(raw: string | null | undefined): string {
  const s = String(raw ?? "").trim().toUpperCase();
  switch (s) {
    case "NEW":
      return "신규";
    case "SUBMITTED":
      return "제출됨";
    case "ACCEPTED":
      return "주문 접수";
    case "PARTIALLY_FILLED":
      return "부분 체결";
    case "FILLED":
      return "체결 완료";
    case "CANCELED":
    case "CANCELLED":
      return "취소";
    case "REJECTED":
      return "거부";
    case "EXPIRED":
      return "만료";
    case "PENDING":
      return "대기";
    default:
      return s ? `확인 필요 (${s})` : "—";
  }
}

export function brokerLabelKo(raw: string | null | undefined): string {
  const s = String(raw ?? "").trim().toUpperCase();
  switch (s) {
    case "UPBIT":
      return "업비트";
    case "KIWOOM":
      return "키움증권";
    case "PAPER":
      return "모의거래(Paper)";
    default:
      return s || "—";
  }
}

export function promotionStatusLabelKo(raw: string | null | undefined): string {
  const s = String(raw ?? "").trim().toUpperCase();
  if (s === "REVIEW READY" || s === "REVIEW_READY") return "적용 검토 가능";
  if (s === "NOT READY" || s === "NOT_READY") return "표본 수집 중";
  if (s.includes("SAMPLE") || s.includes("COLLECT")) return "표본 수집 중";
  return s || "—";
}

/** 금액 KRW 표시 */
export function formatKrwKo(value: unknown): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${new Intl.NumberFormat("ko-KR").format(n)}원`;
}
