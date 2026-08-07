/**
 * 미전송 LIVE PENDING 주문 — 관리자 「미전송 주문 폐기」 버튼 표시 조건.
 * 최종 허용은 서버 preview/retire가 Fail Closed로 판정한다.
 */

export type RetireButtonOrderRow = {
  status_code?: unknown;
  broker_order_id?: unknown;
  submission_attempt_count?: unknown;
  user_broker_account_id?: unknown;
  account_id?: unknown;
  broker_code?: unknown;
};

export function canShowUnsubmittedRetireButton(
  row: RetireButtonOrderRow | null | undefined,
): boolean {
  if (!row) return false;
  const status = String(row.status_code ?? "").toUpperCase();
  if (status !== "PENDING") return false;
  const brokerId = row.broker_order_id;
  if (brokerId != null && String(brokerId).trim() !== "") return false;
  const attempts = Number(row.submission_attempt_count ?? 0);
  if (!Number.isFinite(attempts) || attempts !== 0) return false;
  if (row.user_broker_account_id == null || row.user_broker_account_id === "") {
    return false;
  }
  if (row.account_id != null && row.account_id !== "") return false;
  const broker = String(row.broker_code ?? "").toUpperCase();
  return broker === "UPBIT" || broker === "KIWOOM";
}
