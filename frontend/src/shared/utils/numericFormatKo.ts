/**
 * 사용자 노출용 숫자 포맷 — 지수표기(0E-8) 방지.
 * DB/API 내부 값은 변경하지 않고 화면 표시만 정규화한다.
 */

/** 문자열/숫자를 안전하게 finite number로 파싱 (지수표기 포함) */
export function parseDecimalSafe(value: unknown): number | null {
  if (value == null || value === "") return null;
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  const raw = String(value).trim();
  if (!raw || raw === "—" || raw === "-") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/** 0 / -0 / 0E-n 을 0으로 판정 */
export function isEffectivelyZero(value: unknown): boolean {
  const n = parseDecimalSafe(value);
  return n === null || n === 0;
}

/** 불필요한 trailing zero 제거 (0.927643780000 → 0.92764378) */
function trimTrailingZeros(formatted: string): string {
  if (!formatted.includes(".")) return formatted;
  return formatted.replace(/\.?0+$/, "");
}

/** 수량 — 0이면 "0", 양수는 필요한 소수만 */
export function formatQuantityKo(value: unknown): string {
  const n = parseDecimalSafe(value);
  if (n === null) return "—";
  if (n === 0) return "0";
  const abs = Math.abs(n);
  const maxFrac = abs >= 1 ? 8 : 12;
  const s = trimTrailingZeros(
    n.toLocaleString("ko-KR", {
      maximumFractionDigits: maxFrac,
      useGrouping: false,
    }),
  );
  return s;
}

/** 가격 — 콤마 + 원 (0 → 0원) */
export function formatPriceKo(value: unknown): string {
  const n = parseDecimalSafe(value);
  if (n === null) return "—";
  if (n === 0) return "0원";
  return `${new Intl.NumberFormat("ko-KR").format(n)}원`;
}

/** 일반 소수 — 지수표기 방지 */
export function formatDecimalKo(value: unknown): string {
  const n = parseDecimalSafe(value);
  if (n === null) return "—";
  if (n === 0) return "0";
  const abs = Math.abs(n);
  const maxFrac = abs >= 1 ? 8 : 12;
  return trimTrailingZeros(
    n.toLocaleString("ko-KR", {
      maximumFractionDigits: maxFrac,
      useGrouping: abs >= 1000,
    }),
  );
}

/** 평가금액/손익 — 정수 원 단위 */
export function formatAmountKo(value: unknown): string {
  const n = parseDecimalSafe(value);
  if (n === null) return "—";
  if (n === 0) return "0원";
  return `${new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: 0,
  }).format(Math.round(n))}원`;
}

/** cell() 대체 — 숫자형 문자열이면 지수표기 없이 표시 */
export function formatCellNumeric(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  const raw = String(value).trim();
  if (!raw) return "—";
  if (/[eE]/.test(raw)) {
    const n = parseDecimalSafe(raw);
    if (n !== null) return formatDecimalKo(n);
  }
  const n = parseDecimalSafe(raw);
  if (n !== null) return formatDecimalKo(n);
  return raw;
}
