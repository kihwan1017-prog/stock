/**
 * Risk 설정 UI용 rate(소수) ↔ percent 변환 (순수 계산).
 * Kill / system mutation / LIVE 로직 없음.
 */

export function rateToPercent(value: unknown): number | undefined {
  if (value == null || value === "") return undefined;
  const n = Number(value);
  if (Number.isNaN(n)) return undefined;
  return Number((n * 100).toFixed(4));
}

export function percentToRate(value: number | null | undefined): number | null {
  if (value == null) return null;
  return Number((value / 100).toFixed(6));
}
