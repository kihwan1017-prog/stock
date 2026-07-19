/** STEP46 — 가중치 정규화 (합=1) */
export function normalizeWeights(weights: number[]): number[] {
  const sum = weights.reduce((acc, w) => acc + (Number.isFinite(w) ? w : 0), 0);
  if (sum <= 0) return weights.map(() => 0);
  return weights.map((w) => (Number.isFinite(w) ? w : 0) / sum);
}
