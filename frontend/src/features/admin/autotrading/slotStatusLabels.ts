/**
 * Portfolio Slot / 운영 상태 → 사용자 친화 한국어.
 */

export function slotStatusLabelKo(status: string | null | undefined): string {
  const s = String(status ?? "").trim().toUpperCase();
  switch (s) {
    case "WAITING_SIGNAL":
      return "매수조건 감시 중";
    case "ENTRY_PENDING":
      return "매수 주문 처리 중";
    case "OPEN":
      return "보유 중";
    case "EXIT_PENDING":
      return "매도 주문 처리 중";
    case "COOLDOWN":
      return "재진입 대기";
    case "EMPTY":
      return "후보 대기";
    case "ERROR":
      return "오류";
    default:
      return s ? `확인 필요 (${s})` : "—";
  }
}

export function unattendedLeaseLabelKo(
  status: string | null | undefined,
): string {
  const s = String(status ?? "").trim().toUpperCase();
  switch (s) {
    case "ACTIVE":
      return "24H 무인운영 활성";
    case "PROTECTIVE_EXIT_ONLY":
      return "신규 진입 중지 · 기존 포지션 보호만 수행";
    case "EXPIRED":
      return "24H 승인 만료";
    case "DISABLED":
    case "OFF":
      return "24H 무인운영 꺼짐";
    default:
      return s || "—";
  }
}

export function autoTradingStateLabelKo(
  state: string | null | undefined,
): string {
  const s = String(state ?? "").trim().toUpperCase();
  switch (s) {
    case "RUNNING":
      return "자동매매 가동 중";
    case "WAITING_SIGNAL":
      return "매수조건 대기";
    case "DEGRADED":
      return "일부 장애 · 점검 필요";
    case "BLOCKED":
      return "차단됨";
    case "STOPPED":
      return "중지";
    case "READY_FOR_AUTO_TRADING":
      return "자동매매 준비 완료";
    default:
      return s || "—";
  }
}

/** 상대 시각 (초) → "3초 전" */
export function formatAgeKo(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "—";
  const s = Math.max(0, Math.floor(Number(seconds)));
  if (s < 60) return `${s}초 전`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}분 전`;
  const h = Math.floor(m / 60);
  return `${h}시간 ${m % 60}분 전`;
}

export function formatIsoAgeKo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(String(iso));
  if (!Number.isFinite(t)) return "—";
  return formatAgeKo((Date.now() - t) / 1000);
}
