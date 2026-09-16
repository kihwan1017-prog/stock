/**
 * AMBIGUOUS/MANUAL_REVIEW Outbox — 「미전송 확인 후 폐기」 버튼 표시 조건.
 * 최종 허용은 서버 resolve preview가 Fail Closed로 판정한다.
 */

export type ResolveNotSubmittedOrderRow = {
  status_code?: unknown;
  broker_order_id?: unknown;
  submission_attempt_count?: unknown;
  user_broker_account_id?: unknown;
  account_id?: unknown;
  broker_code?: unknown;
};

export type OutboxStatusHint = {
  order_id?: unknown;
  status_code?: unknown;
  event_type?: unknown;
};

const AMBIGUOUS_OUTBOX = new Set(["AMBIGUOUS", "MANUAL_REVIEW"]);

export function outboxStatusForOrder(
  orderId: number,
  outboxRows: OutboxStatusHint[] | null | undefined,
): string | null {
  if (!Array.isArray(outboxRows) || !Number.isFinite(orderId)) return null;
  const submit = outboxRows.filter(
    (r) =>
      Number(r.order_id) === orderId &&
      String(r.event_type ?? "SUBMIT_ORDER").toUpperCase() === "SUBMIT_ORDER",
  );
  if (submit.length === 0) return null;
  // 최신 추정: 배열 앞쪽이 최신인 경우와 뒤쪽이 최신인 경우 모두 허용 — AMBIGUOUS 우선
  for (const row of submit) {
    const st = String(row.status_code ?? "").toUpperCase();
    if (AMBIGUOUS_OUTBOX.has(st)) return st;
  }
  return String(submit[0]?.status_code ?? "").toUpperCase() || null;
}

export function canShowResolveNotSubmittedButton(
  row: ResolveNotSubmittedOrderRow | null | undefined,
  outboxStatus: string | null | undefined,
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
  if (broker !== "UPBIT") return false;
  const ox = String(outboxStatus ?? "").toUpperCase();
  return AMBIGUOUS_OUTBOX.has(ox);
}
