/**
 * UPBIT portfolio/entry policy 표시·검증 헬퍼.
 */

import { asRecord } from "@/shared/utils/dataHelpers";

export const PORTFOLIO_POLICY_CONFIRM_TEXT =
  "자동매매 진입 및 후보 선정 정책을 변경합니다. 현재 보유 포지션에는 즉시 강제 주문을 발생시키지 않습니다.";

export const ENTRY_FUNNEL_STEPS = [
  "AI 매수 허용 (ALLOW)",
  "MA 추세 (단기 > 장기)",
  "MA 간격",
  "RSI",
  "거래량 (Volume Surge)",
  "Risk / Portfolio",
  "주문",
] as const;

export function formatMinutesFromSeconds(sec: unknown): string {
  const n = Number(sec);
  if (!Number.isFinite(n) || n <= 0) return "—";
  if (n < 3600) return `${Math.round(n / 60)}분`;
  const h = Math.floor(n / 3600);
  const m = Math.round((n % 3600) / 60);
  return m > 0 ? `${h}시간 ${m}분` : `${h}시간`;
}

export function formatWaitingAge(seconds: unknown): string {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 3600) return `${Math.round(n / 60)}분`;
  const h = Math.floor(n / 3600);
  const m = Math.round((n % 3600) / 60);
  return `${h}시간 ${m > 0 ? `${m}분` : ""}`.trim();
}

export function policyDisplayRecord(policy: unknown): Record<string, unknown> {
  return asRecord(policy) ?? {};
}

export function entryPolicyLabel(raw: unknown): string {
  const v = String(raw ?? "CROSS_EVENT").toUpperCase();
  if (v === "BULLISH_STATE" || v === "TREND_STATE") return "BULLISH_STATE";
  return v;
}

export function validatePolicyFormValues(
  values: Record<string, unknown>,
): string | null {
  const short = values.short_ma_window;
  const long = values.long_ma_window;
  if (
    short != null &&
    long != null &&
    Number.isFinite(Number(short)) &&
    Number.isFinite(Number(long)) &&
    Number(short) >= Number(long)
  ) {
    return "단기 MA는 장기 MA보다 작아야 합니다.";
  }
  const maxPos = values.max_positions;
  if (maxPos != null && (Number(maxPos) < 1 || Number(maxPos) > 10)) {
    return "최대 후보 슬롯은 1~10 사이여야 합니다.";
  }
  return null;
}
