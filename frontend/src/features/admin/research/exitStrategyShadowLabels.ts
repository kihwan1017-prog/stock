/** Exit Shadow checkpoint label — UI helper (REAL promote 아님). */

export function classifyCheckpointLabel(n: number): string {
  if (n < 30) return "INSUFFICIENT";
  if (n < 50) return "SANITY_ONLY";
  if (n < 100) return "EARLY_SIGNAL";
  if (n < 200) return "CANDIDATE";
  if (n < 300) return "VALIDATION";
  return "PROMOTION_REVIEW_ELIGIBLE";
}
