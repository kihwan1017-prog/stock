/**
 * Research Detail UI helpers — null-safe format / array guard.
 */

import {
  formatDecimalKo,
  formatPriceKo,
  parseDecimalSafe,
} from "@/shared/utils/numericFormatKo";

export function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function dash(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number" && !Number.isFinite(value)) return "—";
  return String(value);
}

export function formatPctResearch(value: unknown, digits = 2): string {
  const n = parseDecimalSafe(value);
  if (n === null) return "—";
  return `${n.toLocaleString("ko-KR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })}%`;
}

export function formatPriceResearch(value: unknown): string {
  return formatPriceKo(value);
}

export function formatNumResearch(
  value: unknown,
  digitsOrRecord?: number | Record<string, unknown>,
): string {
  // Table render(value, record) 와 formatNumResearch(v, digits) 모두 수용
  void digitsOrRecord;
  return formatDecimalKo(value);
}

export function formatKstClock(iso: unknown): string {
  if (iso == null || iso === "") return "—";
  const s = String(iso);
  try {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString("ko-KR", {
        timeZone: "Asia/Seoul",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
    }
  } catch {
    /* ignore */
  }
  return s;
}
