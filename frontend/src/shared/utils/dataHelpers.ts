import { formatCellNumeric } from "@/shared/utils/numericFormatKo";

/** 응답에서 테이블용 행 배열을 안전하게 추출 (Admin/User 공용 · scope 무관) */

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

/**
 * UI 표시용 빈 객체 fallback.
 * LOADING/EMPTY/ERROR 분기는 호출부에서 먼저 처리한 뒤 사용한다.
 */
export function asRecordOrEmpty(value: unknown): Record<string, unknown> {
  return asRecord(value) ?? {};
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
  const raw = String(value);
  if (/[eE]/.test(raw) || /^-?\d+(\.\d+)?$/.test(raw.trim())) {
    return formatCellNumeric(value).replace(/—/g, "-");
  }
  return raw;
}
