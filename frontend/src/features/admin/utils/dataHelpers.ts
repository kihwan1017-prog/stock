/** 응답에서 테이블용 행 배열을 안전하게 추출 */

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

export function extractRows(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) {
    return data.filter(
      (item): item is Record<string, unknown> =>
        typeof item === "object" && item !== null,
    );
  }
  const obj = asRecord(data);
  if (!obj) return [];

  for (const key of [
    "items",
    "candidates",
    "orders",
    "executions",
    "events",
    "jobs",
    "rows",
    "results",
    "news",
    "models",
    "tables",
    "disclosures",
    "channels",
    "accounts",
  ]) {
    const value = obj[key];
    if (Array.isArray(value)) {
      return value.filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      );
    }
  }
  return [];
}

export function cell(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}
