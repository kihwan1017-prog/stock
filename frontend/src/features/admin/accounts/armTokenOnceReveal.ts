/**
 * ARM ON 응답의 원문 토큰 1회 표시용 순수 헬퍼.
 * 원문은 React state에만 두고 localStorage/sessionStorage/로그에 넣지 않는다.
 */

export type ArmTokenOnceReveal = {
  ubaId: number;
  armToken: string;
  expiresAt: string;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/**
 * ARM ON 성공 응답에서 1회 표시 페이로드를 추출한다.
 * already_armed 이거나 arm_token 원문이 없으면 null (재표시 금지).
 */
export function parseArmOnSuccessPayload(
  data: unknown,
  ubaId: number,
): ArmTokenOnceReveal | null {
  const record = asRecord(data);
  if (!record) return null;
  if (record.already_armed === true) return null;

  const armToken = String(record.arm_token ?? "").trim();
  if (!armToken) return null;

  const expiresAt = String(
    record.arm_expires_at ?? record.expires_at ?? "",
  ).trim();
  if (!expiresAt) return null;

  return { ubaId, armToken, expiresAt };
}

/** 토큰 마스킹 — revealed=false 시 앞·뒤 일부만 */
export function maskArmToken(token: string, revealed: boolean): string {
  if (revealed) return token;
  const raw = String(token ?? "");
  if (raw.length <= 8) {
    return "•".repeat(Math.max(raw.length, 8));
  }
  const head = raw.slice(0, 4);
  const tail = raw.slice(-4);
  const middleLen = Math.min(Math.max(raw.length - 8, 4), 24);
  return `${head}${"•".repeat(middleLen)}${tail}`;
}

export type ArmCountdown = {
  remainingSeconds: number;
  expired: boolean;
  label: string;
};

/** 만료까지 카운트다운 라벨 */
export function formatArmCountdown(
  expiresAtIso: string,
  nowMs: number = Date.now(),
): ArmCountdown {
  const expiresMs = Date.parse(expiresAtIso);
  if (Number.isNaN(expiresMs)) {
    return {
      remainingSeconds: 0,
      expired: true,
      label: "만료시각 파싱 실패",
    };
  }
  const remainingSeconds = Math.max(
    0,
    Math.floor((expiresMs - nowMs) / 1000),
  );
  const expired = remainingSeconds <= 0;
  if (expired) {
    return { remainingSeconds: 0, expired: true, label: "만료됨" };
  }
  const minutes = Math.floor(remainingSeconds / 60);
  const seconds = remainingSeconds % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return {
    remainingSeconds,
    expired: false,
    label: `${mm}:${ss} 남음 (${remainingSeconds}초)`,
  };
}

/**
 * 재발급 안내 — Scheduler PAUSE일 때만 DISARM→ARM 재발급 절차를 안내.
 * RUN 중이면 먼저 PAUSE하도록 유도한다.
 */
export function armReissueGuidance(schedulerPaused: boolean): string {
  if (schedulerPaused) {
    return "원문 토큰 재확인은 불가합니다. Scheduler PAUSE 상태에서 DISARM 후 ARM을 다시 실행하면 새 토큰이 1회 발급됩니다.";
  }
  return "원문 토큰 재확인은 불가합니다. 먼저 Scheduler를 PAUSE한 뒤 DISARM → ARM으로 재발급하세요.";
}
