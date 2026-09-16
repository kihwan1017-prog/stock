/**
 * 주문·체결 모니터링 — 오늘(KST) 필터/집계 (READ projection only).
 */

import { resolveOrderTradingKind } from "@/features/admin/autotrading/orderOwnership";

export type MarketFilter = "ALL" | "UPBIT" | "KIWOOM";
export type OwnershipFilter = "ALL" | "AUTO" | "MANUAL" | "UNKNOWN";

export type OrderRow = Record<string, unknown>;

const FILLED = new Set(["FILLED", "DONE", "COMPLETED", "PARTIAL"]);
const CANCELLED = new Set(["CANCELLED", "CANCELED", "REJECTED", "EXPIRED"]);
const OPENISH = new Set([
  "NEW",
  "ACCEPTED",
  "SUBMITTED",
  "PENDING",
  "PARTIAL",
  "OPEN",
]);

export function kstTodayStartIso(): string {
  const now = new Date();
  const kst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const y = kst.getUTCFullYear();
  const m = String(kst.getUTCMonth() + 1).padStart(2, "0");
  const d = String(kst.getUTCDate()).padStart(2, "0");
  // KST midnight as +09:00
  return `${y}-${m}-${d}T00:00:00+09:00`;
}

export function parseTs(value: unknown): Date | null {
  if (value == null || value === "") return null;
  const d = new Date(String(value));
  return Number.isFinite(d.getTime()) ? d : null;
}

export function isOnOrAfterKstToday(value: unknown, todayStart: Date): boolean {
  const d = parseTs(value);
  if (!d) return false;
  return d.getTime() >= todayStart.getTime();
}

export function brokerOf(row: OrderRow): string {
  return String(row.broker_code ?? row.exchange_code ?? "")
    .toUpperCase()
    .replace("KRX", "KIWOOM");
}

export function matchesMarket(row: OrderRow, market: MarketFilter): boolean {
  if (market === "ALL") return true;
  const b = brokerOf(row);
  if (market === "UPBIT") return b === "UPBIT";
  return b === "KIWOOM" || b === "KRX";
}

export function matchesOwnership(
  row: OrderRow,
  ownership: OwnershipFilter,
): boolean {
  if (ownership === "ALL") return true;
  return resolveOrderTradingKind(row).kind === ownership;
}

export function filterOrdersForMonitor(
  rows: OrderRow[],
  opts: {
    market: MarketFilter;
    ownership: OwnershipFilter;
    symbol?: string;
    todayOnly?: boolean;
    todayStart?: Date;
  },
): OrderRow[] {
  const todayStart = opts.todayStart ?? new Date(kstTodayStartIso());
  const sym = (opts.symbol || "").trim().toUpperCase();
  return rows.filter((row) => {
    if (!matchesMarket(row, opts.market)) return false;
    if (!matchesOwnership(row, opts.ownership)) return false;
    if (sym && String(row.symbol ?? "").toUpperCase() !== sym) return false;
    if (opts.todayOnly !== false) {
      const ts = row.filled_at ?? row.created_at;
      if (!isOnOrAfterKstToday(ts, todayStart)) return false;
    }
    return true;
  });
}

export type DayOrderSummary = {
  buyCount: number;
  sellCount: number;
  filledCount: number;
  openCount: number;
  cancelledCount: number;
};

export function summarizeDayOrders(rows: OrderRow[]): DayOrderSummary {
  let buyCount = 0;
  let sellCount = 0;
  let filledCount = 0;
  let openCount = 0;
  let cancelledCount = 0;
  for (const row of rows) {
    const side = String(row.side_code ?? row.side ?? "").toUpperCase();
    const st = String(row.status_code ?? row.status ?? "").toUpperCase();
    if (side === "BUY") buyCount += 1;
    if (side === "SELL") sellCount += 1;
    if (FILLED.has(st) || Number(row.filled_quantity ?? 0) > 0) {
      filledCount += 1;
    }
    if (OPENISH.has(st) && !FILLED.has(st)) openCount += 1;
    if (CANCELLED.has(st)) cancelledCount += 1;
  }
  return { buyCount, sellCount, filledCount, openCount, cancelledCount };
}

export type HourlyFlowPoint = {
  hour: string;
  buy: number;
  sell: number;
  label: string;
};

/** 시간대별 체결 건수 — filled 우선, 없으면 created. */
export function buildHourlyFillFlow(rows: OrderRow[]): HourlyFlowPoint[] {
  const buckets = new Map<string, { buy: number; sell: number }>();
  for (let h = 0; h < 24; h += 1) {
    const key = String(h).padStart(2, "0");
    buckets.set(key, { buy: 0, sell: 0 });
  }
  for (const row of rows) {
    const st = String(row.status_code ?? "").toUpperCase();
    const filledQty = Number(row.filled_quantity ?? 0);
    if (!FILLED.has(st) && !(filledQty > 0)) continue;
    const ts = parseTs(row.filled_at ?? row.created_at);
    if (!ts) continue;
    // KST hour
    const kstMs = ts.getTime() + 9 * 60 * 60 * 1000;
    const hour = new Date(kstMs).getUTCHours();
    const key = String(hour).padStart(2, "0");
    const b = buckets.get(key)!;
    const side = String(row.side_code ?? row.side ?? "").toUpperCase();
    if (side === "BUY") b.buy += 1;
    else if (side === "SELL") b.sell += 1;
  }
  return [...buckets.entries()].map(([hour, v]) => ({
    hour,
    label: `${hour}:00`,
    buy: v.buy,
    sell: v.sell,
  }));
}

export type TimelineTooltipRow = {
  time: string;
  symbol: string;
  side: string;
  price: string;
  qty: string;
  ownership: string;
  exitReason?: string;
  pnl?: string;
};

export function filledOrdersForTooltip(
  rows: OrderRow[],
  hourKey: string,
  closedByOrderId?: Map<number, Record<string, unknown>>,
): TimelineTooltipRow[] {
  const out: TimelineTooltipRow[] = [];
  for (const row of rows) {
    const st = String(row.status_code ?? "").toUpperCase();
    const filledQty = Number(row.filled_quantity ?? 0);
    if (!FILLED.has(st) && !(filledQty > 0)) continue;
    const ts = parseTs(row.filled_at ?? row.created_at);
    if (!ts) continue;
    const kstMs = ts.getTime() + 9 * 60 * 60 * 1000;
    const hour = String(new Date(kstMs).getUTCHours()).padStart(2, "0");
    if (hour !== hourKey) continue;
    const own = resolveOrderTradingKind(row);
    const oid = Number(row.order_id ?? row.id);
    const trip =
      Number.isFinite(oid) && closedByOrderId
        ? closedByOrderId.get(oid)
        : undefined;
    const net = trip ? numOrNull(trip.net_pnl) : null;
    out.push({
      time: ts.toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }),
      symbol: String(row.symbol ?? "—"),
      side: String(row.side_code ?? row.side ?? "—"),
      price: String(row.average_fill_price ?? row.order_price ?? "—"),
      qty: String(row.filled_quantity ?? row.order_quantity ?? "—"),
      ownership: own.labelKo,
      exitReason: trip
        ? String(trip.exit_reason_label_ko ?? trip.exit_reason_category ?? "")
        : undefined,
      pnl: net != null ? String(net) : undefined,
    });
  }
  return out.slice(0, 8);
}

export function numOrNull(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
