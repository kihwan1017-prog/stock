/** STEP43 — 평가금액 기준 보유 비중(%) 계산 */
export function computeHoldingWeights(
  marketValues: number[],
): number[] {
  const total = marketValues.reduce(
    (sum, value) => sum + (Number.isFinite(value) ? value : 0),
    0,
  );
  if (total <= 0) {
    return marketValues.map(() => 0);
  }
  return marketValues.map((value) => {
    const safe = Number.isFinite(value) ? value : 0;
    return (safe / total) * 100;
  });
}

/** 종목 수익률(%) = (평가손익 / 원가) * 100 */
export function computeReturnRate(
  marketValue: number,
  costValue: number,
): number {
  if (!Number.isFinite(costValue) || costValue <= 0) {
    return 0;
  }
  if (!Number.isFinite(marketValue)) {
    return 0;
  }
  return ((marketValue - costValue) / costValue) * 100;
}
