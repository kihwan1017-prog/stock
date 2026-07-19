const OPEN_STATUSES = new Set([
  "NEW",
  "ACCEPTED",
  "PARTIAL",
  "WORKING",
  "OPEN",
  "SUBMITTED",
  "",
]);

/** STEP44 — 미체결/진행중 주문 필터 */
export function isOpenOrderStatus(status: unknown): boolean {
  return OPEN_STATUSES.has(String(status ?? "").toUpperCase());
}

export function filterOpenOrders(
  rows: Record<string, unknown>[],
  statusFields: string[] = ["status_code", "status"],
): Record<string, unknown>[] {
  return rows.filter((row) => {
    for (const field of statusFields) {
      if (field in row) {
        return isOpenOrderStatus(row[field]);
      }
    }
    return isOpenOrderStatus("");
  });
}
