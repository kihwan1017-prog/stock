/**
 * 주문 탭/필터 헬퍼 — presentation only.
 */

export type OrderListTab = "open" | "fills" | "rejected" | "all";

export const ORDER_LIST_TAB_LABELS: Record<OrderListTab, string> = {
  open: "진행 주문",
  fills: "체결",
  rejected: "취소·거부",
  all: "전체",
};

const OPEN_STATUSES = new Set([
  "NEW",
  "PENDING",
  "SUBMITTED",
  "ACCEPTED",
  "PARTIAL",
  "PARTIALLY_FILLED",
  "OPEN",
  "WORKING",
  "QUEUED",
  "SENDING",
]);

const FILL_STATUSES = new Set([
  "FILLED",
  "FULLY_FILLED",
  "DONE",
  "COMPLETED",
]);

const REJECT_STATUSES = new Set([
  "CANCELLED",
  "CANCELED",
  "REJECTED",
  "FAILED",
  "EXPIRED",
  "RETIRED",
  "CONFIRMED_NOT_SUBMITTED",
]);

export function orderMatchesTab(
  statusCode: string | null | undefined,
  filledQty: unknown,
  tab: OrderListTab,
): boolean {
  if (tab === "all") return true;
  const st = String(statusCode ?? "").toUpperCase();
  const filled = Number(filledQty ?? 0);
  if (tab === "fills") {
    return FILL_STATUSES.has(st) || (Number.isFinite(filled) && filled > 0 && !OPEN_STATUSES.has(st));
  }
  if (tab === "rejected") {
    return REJECT_STATUSES.has(st);
  }
  // open
  if (OPEN_STATUSES.has(st)) return true;
  if (FILL_STATUSES.has(st) || REJECT_STATUSES.has(st)) return false;
  return !FILL_STATUSES.has(st) && !REJECT_STATUSES.has(st);
}
