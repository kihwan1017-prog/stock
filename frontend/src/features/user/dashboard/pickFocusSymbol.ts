/** STEP42 — 뉴스/공시 포커스 심볼 선택 (AI 1위 → 보유 1위 → fallback) */
export function pickFocusSymbol(
  aiRows: Array<{ symbol?: unknown }>,
  positionRows: Array<{ symbol?: unknown }>,
  fallback = "005930",
): string {
  const fromAi = aiRows[0]?.symbol;
  if (fromAi) return String(fromAi).toUpperCase();
  const fromPos = positionRows[0]?.symbol;
  if (fromPos) return String(fromPos).toUpperCase();
  return fallback;
}
