/** 프론트 표시용 MDD (%) — Backend 공식과 동일. */

export function computeMaxDrawdownPct(equities: number[]): number {
  if (equities.length === 0) return 0;
  let peak = equities[0];
  let maxDd = 0;
  for (const equity of equities) {
    if (equity > peak) peak = equity;
    if (peak > 0) {
      const dd = (peak - equity) / peak;
      if (dd > maxDd) maxDd = dd;
    }
  }
  return maxDd * 100;
}
