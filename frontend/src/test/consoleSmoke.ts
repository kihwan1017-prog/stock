/**
 * antd / Next console warning smoke helper.
 * 외부 라이브러리 noise는 allowlist, 치명·deprecated는 fail.
 */

const FAIL_PATTERNS = [
  /\[antd:/i,
  /deprecated/i,
  /Cannot read properties of (undefined|null)/i,
  /Element type is invalid/i,
  /React does not recognize/i,
  /Each child in a list should have a unique ["']key["']/i,
  /Table is not defined/i,
  /Hydration failed/i,
];

/** 최소 allowlist — 신규 추가는 근거와 함께만 */
const ALLOWLIST: RegExp[] = [
  // React Query devtools 등 개발 전용 (테스트 기본 off)
];

export type ConsoleCapture = {
  warnings: string[];
  errors: string[];
  restore: () => void;
};

export function startConsoleCapture(): ConsoleCapture {
  const warnings: string[] = [];
  const errors: string[] = [];
  const origWarn = console.warn;
  const origError = console.error;

  const push = (bucket: string[], args: unknown[]) => {
    const text = args
      .map((a) => {
        if (typeof a === "string") return a;
        try {
          return JSON.stringify(a);
        } catch {
          return String(a);
        }
      })
      .join(" ");
    if (ALLOWLIST.some((re) => re.test(text))) return;
    bucket.push(text);
  };

  console.warn = (...args: unknown[]) => {
    push(warnings, args);
    origWarn.apply(console, args as Parameters<typeof console.warn>);
  };
  console.error = (...args: unknown[]) => {
    push(errors, args);
    origError.apply(console, args as Parameters<typeof console.error>);
  };

  return {
    warnings,
    errors,
    restore: () => {
      console.warn = origWarn;
      console.error = origError;
    },
  };
}

export function failingConsoleLines(capture: ConsoleCapture): string[] {
  const all = [...capture.errors, ...capture.warnings];
  return all.filter((line) => FAIL_PATTERNS.some((re) => re.test(line)));
}

export function assertNoAntdConsoleNoise(capture: ConsoleCapture): void {
  const bad = failingConsoleLines(capture);
  if (bad.length > 0) {
    throw new Error(
      `Forbidden console noise (${bad.length}):\n${bad.slice(0, 20).join("\n")}`,
    );
  }
}
