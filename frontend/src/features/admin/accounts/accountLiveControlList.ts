/**
 * UPBIT + KIWOOM 계좌 LIVE 제어 목록 병합/필터.
 * Backend list API는 broker_code 기본값이 UPBIT이므로 브로커별 조회 후 합친다.
 */

import { extractRows } from "@/features/admin/utils/dataHelpers";

export const LIVE_CONTROL_BROKERS = ["UPBIT", "KIWOOM"] as const;

export type LiveControlBrokerFilter = "ALL" | "UPBIT" | "KIWOOM";

export function brokersForFilter(
  filter: LiveControlBrokerFilter,
): readonly (typeof LIVE_CONTROL_BROKERS)[number][] {
  if (filter === "ALL") return LIVE_CONTROL_BROKERS;
  return [filter];
}

export function rowUbaId(row: Record<string, unknown>): number {
  return Number(row.user_broker_account_id ?? row.account_id ?? 0);
}

export function rowBrokerCode(row: Record<string, unknown>): string {
  return String(row.broker_code ?? row.account_type ?? "").toUpperCase();
}

export function mergeBrokerAccountLists(
  lists: unknown[],
): Record<string, unknown>[] {
  const byId = new Map<number, Record<string, unknown>>();
  for (const list of lists) {
    const rows = extractRows(list) as Record<string, unknown>[];
    for (const row of rows) {
      const id = rowUbaId(row);
      if (!Number.isInteger(id) || id < 1) continue;
      const broker = rowBrokerCode(row);
      if (
        broker !== "UPBIT" &&
        broker !== "KIWOOM"
      ) {
        continue;
      }
      byId.set(id, row);
    }
  }
  return [...byId.values()].sort((a, b) => rowUbaId(a) - rowUbaId(b));
}

export function filterRowsByBroker(
  rows: Record<string, unknown>[],
  filter: LiveControlBrokerFilter,
): Record<string, unknown>[] {
  if (filter === "ALL") return rows;
  return rows.filter((row) => rowBrokerCode(row) === filter);
}

export function hasUba(
  rows: Record<string, unknown>[],
  ubaId: number,
): boolean {
  return rows.some((row) => rowUbaId(row) === ubaId);
}
