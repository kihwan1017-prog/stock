/** STEP48 — 관심종목 API 전, 보유 포지션에서 심볼 추출 */
export function pickInterestSymbols(
  positionRows: Array<{ symbol?: unknown }>,
  limit = 5,
): string[] {
  const seen = new Set<string>();
  const symbols: string[] = [];

  for (const row of positionRows) {
    if (row.symbol === null || row.symbol === undefined || row.symbol === "") {
      continue;
    }
    const symbol = String(row.symbol).trim().toUpperCase();
    if (!symbol || seen.has(symbol)) continue;
    seen.add(symbol);
    symbols.push(symbol);
    if (symbols.length >= limit) break;
  }

  return symbols;
}
