/**
 * Mobile overview types + format helpers (READ-ONLY).
 */

import { mapStatus } from "@/features/admin/system-status/statusLabelMap";

export type MobileOverview = {
  updated_at?: string;
  overall?: { status?: string; label_hint?: string };
  system?: Record<string, unknown>;
  upbit?: Record<string, unknown>;
  kiwoom?: Record<string, unknown>;
  today?: Record<string, unknown>;
  positions?: { count?: number; items?: Record<string, unknown>[] };
  recent_orders?: Record<string, unknown>[];
  recent_events?: Record<string, unknown>[];
  ai?: Record<string, unknown>;
};

export function formatKrwSigned(value: unknown): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(Math.round(n)).toLocaleString("ko-KR");
  if (n > 0) return `+${abs}원`;
  if (n < 0) return `-${abs}원`;
  return `${abs}원`;
}

export function pnlClass(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "neutral";
  return n > 0 ? "pos" : "neg";
}

export function statusKo(raw: unknown): string {
  return mapStatus(raw).labelKo;
}

export function overallEmoji(status: unknown): string {
  const s = String(status || "").toUpperCase();
  if (s === "HEALTHY") return "🟢";
  if (s === "STOPPED" || s === "BLOCKED") return "🔴";
  return "🟠";
}

export function boolOnOff(v: unknown): string {
  return v === true || String(v).toUpperCase() === "ON" || String(v).toUpperCase() === "TRUE"
    ? "ON"
    : "OFF";
}

/** LIVE/ARM 조합 → 사용자 문구 (모바일 자동매매 탭) */
export function formatLiveArmLabel(live: unknown, arm: unknown): string {
  const liveOn =
    live === true ||
    String(live).toUpperCase() === "ON" ||
    String(live).toUpperCase() === "TRUE";
  const armOn =
    arm === true ||
    String(arm).toUpperCase() === "ON" ||
    String(arm).toUpperCase() === "TRUE";
  if (liveOn && armOn) return "자동매매 실행 가능";
  if (liveOn && !armOn) return "LIVE만 켜짐 — ARM 필요";
  if (!liveOn && armOn) return "ARM만 켜짐 — LIVE 필요";
  return "자동매매 중지";
}

export function formatClock(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function sideKo(side: unknown): string {
  const s = String(side || "").toUpperCase();
  if (s === "BUY" || s === "BID") return "매수";
  if (s === "SELL" || s === "ASK") return "매도";
  return s || "—";
}

export function alertEmoji(severity: unknown): string {
  const s = String(severity || "").toUpperCase();
  if (s === "CRITICAL" || s === "ERROR") return "🔴";
  if (s === "WARNING" || s === "WARN") return "🟠";
  return "🟢";
}
