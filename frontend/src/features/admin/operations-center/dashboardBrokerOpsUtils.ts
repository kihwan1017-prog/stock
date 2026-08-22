import { asRecord } from "@/features/admin/utils/dataHelpers";

export function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

export function pickBool(v: unknown): boolean | null {
  if (v === true || v === false) return v;
  const s = String(v ?? "").toUpperCase();
  if (s === "ON" || s === "TRUE" || s === "1") return true;
  if (s === "OFF" || s === "FALSE" || s === "0") return false;
  return null;
}

export function krxPhaseLabelKo(phase: unknown, sessionType: unknown): string {
  const p = String(phase ?? "").toUpperCase();
  const s = String(sessionType ?? "").toUpperCase();
  if (p.includes("REGULAR") || p === "OPEN" || p === "CONTINUOUS") {
    return "장중";
  }
  if (p.includes("PRE") || p === "PREOPEN") return "장전";
  if (p.includes("CLOSE") || p.includes("AFTER") || p === "CLOSED") {
    return "장마감";
  }
  if (s === "HOLIDAY" || p === "HOLIDAY") return "휴장";
  return p || s || "확인 불가";
}
