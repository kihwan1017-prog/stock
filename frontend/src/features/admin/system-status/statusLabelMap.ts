/**
 * 시스템 상태 — 내부 enum은 유지하고 사용자 표시만 한글화.
 */

export type StatusTone = "success" | "processing" | "warning" | "error" | "default";

export type MappedStatus = {
  labelKo: string;
  tone: StatusTone;
};

/** 공통 상태 코드 → 한글/톤 */
export const STATUS_LABEL_MAP: Record<string, MappedStatus> = {
  RUNNING: { labelKo: "실행 중", tone: "success" },
  STOPPED: { labelKo: "중지", tone: "default" },
  PAUSED: { labelKo: "일시정지", tone: "warning" },
  READY: { labelKo: "준비 완료", tone: "success" },
  WAITING: { labelKo: "대기 중", tone: "processing" },
  WAITING_SIGNAL: { labelKo: "신호 대기", tone: "processing" },
  BLOCKED: { labelKo: "차단됨", tone: "error" },
  CONNECTED: { labelKo: "연결됨", tone: "success" },
  DISCONNECTED: { labelKo: "연결 끊김", tone: "error" },
  ACTIVE: { labelKo: "활성", tone: "success" },
  INACTIVE: { labelKo: "비활성", tone: "default" },
  EXPIRED: { labelKo: "만료", tone: "error" },
  EXPIRING: { labelKo: "만료 임박", tone: "warning" },
  ON: { labelKo: "켜짐", tone: "success" },
  OFF: { labelKo: "꺼짐", tone: "default" },
  UP: { labelKo: "정상", tone: "success" },
  DOWN: { labelKo: "중단", tone: "error" },
  OK: { labelKo: "정상", tone: "success" },
  HEALTHY: { labelKo: "정상", tone: "success" },
  DEGRADED: { labelKo: "일부 확인 필요", tone: "warning" },
  ERROR: { labelKo: "오류", tone: "error" },
  FAILED: { labelKo: "실패", tone: "error" },
  CRITICAL: { labelKo: "심각", tone: "error" },
  UNKNOWN: { labelKo: "확인 필요", tone: "default" },
  NOT_AVAILABLE: { labelKo: "없음", tone: "default" },
  N_A: { labelKo: "없음", tone: "default" },
  NA: { labelKo: "없음", tone: "default" },
  CONFIGURED: { labelKo: "설정됨", tone: "success" },
  NOT_CONFIGURED: { labelKo: "미설정", tone: "warning" },
  SKIPPED: { labelKo: "생략", tone: "default" },
  MOCK: { labelKo: "모의", tone: "processing" },
  LIVE: { labelKo: "실거래", tone: "success" },
  REST_ONLY: { labelKo: "REST만", tone: "processing" },
  TRUE: { labelKo: "예", tone: "success" },
  FALSE: { labelKo: "아니오", tone: "default" },
  IN_SYNC: { labelKo: "동기화됨", tone: "success" },
  DRIFT: { labelKo: "불일치", tone: "warning" },
  FEED_REAL_FRESH: { labelKo: "실시간 시세 정상", tone: "success" },
  FEED_STALE: { labelKo: "시세 수신 지연", tone: "warning" },
  REAL_FRESH: { labelKo: "실시간 시세 정상", tone: "success" },
  STALE: { labelKo: "시세 수신 지연", tone: "warning" },
  WARMING_UP: { labelKo: "지표 준비 중", tone: "processing" },
  COLLECTION_ONLY: { labelKo: "데이터 수집 단계", tone: "processing" },
  COLLECTING: { labelKo: "수집 중", tone: "processing" },
  DIAGNOSTIC: { labelKo: "진단 단계", tone: "processing" },
  DIAGNOSTIC_ONLY: { labelKo: "진단 단계", tone: "processing" },
  PRIMARY_REVIEW: { labelKo: "검토 단계", tone: "processing" },
  AVAILABLE: { labelKo: "자동매매 가능", tone: "success" },
  READY_TO_TRADE: { labelKo: "자동매매 가능", tone: "success" },
  AUTO_TRADING_READY: { labelKo: "자동매매 가능", tone: "success" },
  NOT_READY: { labelKo: "준비 안 됨", tone: "warning" },
  PRE_OPEN: { labelKo: "장전", tone: "processing" },
  PREOPEN: { labelKo: "장전", tone: "processing" },
  OPEN: { labelKo: "장중", tone: "success" },
  REGULAR: { labelKo: "장중", tone: "success" },
  CLOSED: { labelKo: "장마감", tone: "default" },
  POST_CLOSE: { labelKo: "장마감", tone: "default" },
  HOLIDAY: { labelKo: "휴장", tone: "default" },
  MARKET_CLOSED: { labelKo: "휴장/마감", tone: "default" },
};

/** blocker 코드 → 한글 (없으면 원문 정리) */
export const BLOCKER_LABEL_MAP: Record<string, string> = {
  LIVE_OFF: "LIVE가 꺼져 있습니다",
  ARM_OFF_OR_EXPIRED: "ARM 승인이 없거나 만료되었습니다",
  ARM_EXPIRED: "ARM 승인이 만료되었습니다",
  ARM_OFF: "ARM이 꺼져 있습니다",
  KILL_SWITCH_ACTIVE: "긴급 중지(Kill Switch)가 활성입니다",
  ACCOUNT_PAUSED: "계좌가 일시정지되었습니다",
  FEED_STALE: "시세 데이터가 지연되고 있습니다",
  RUNTIME_STOPPED: "Runtime이 중지되었습니다",
  RUNNER_STOPPED: "Runner가 중지되었습니다",
  WORKER_STOPPED: "Worker가 중지되었습니다",
  MARKET_CLOSED: "장 마감/휴장입니다",
  WARMUP_INCOMPLETE: "지표 Warmup이 완료되지 않았습니다",
  RISK_BLOCKED: "리스크 한도로 차단되었습니다",
  RECOVERY_LOCK: "복구 잠금 상태입니다",
  CREDENTIAL_MISSING: "브로커 자격증명이 없습니다",
  NOT_CONFIGURED: "설정이 완료되지 않았습니다",
};

export function mapStatus(raw: unknown): MappedStatus {
  if (raw == null || raw === "") {
    return STATUS_LABEL_MAP.UNKNOWN;
  }
  if (typeof raw === "boolean") {
    return raw ? STATUS_LABEL_MAP.TRUE : STATUS_LABEL_MAP.FALSE;
  }
  const key = String(raw).trim().toUpperCase().replace(/\s+/g, "_");
  if (STATUS_LABEL_MAP[key]) return STATUS_LABEL_MAP[key];
  // 부분 매칭
  if (key.includes("RUNNING")) return STATUS_LABEL_MAP.RUNNING;
  if (key.includes("STOP")) return STATUS_LABEL_MAP.STOPPED;
  if (key.includes("STALE")) return STATUS_LABEL_MAP.STALE;
  if (key.includes("FRESH")) return STATUS_LABEL_MAP.REAL_FRESH;
  if (key.includes("CONNECT")) {
    return key.includes("DIS")
      ? STATUS_LABEL_MAP.DISCONNECTED
      : STATUS_LABEL_MAP.CONNECTED;
  }
  return { labelKo: String(raw), tone: "default" };
}

export function mapBlocker(code: unknown): string {
  const key = String(code ?? "").trim().toUpperCase();
  if (!key) return "확인 필요";
  if (BLOCKER_LABEL_MAP[key]) return BLOCKER_LABEL_MAP[key];
  return key
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/^\w/, (c) => c.toUpperCase());
}

export function overallStatusKo(raw: unknown): { title: string; tone: StatusTone } {
  const m = mapStatus(raw);
  const key = String(raw ?? "").toUpperCase();
  if (["UP", "OK", "HEALTHY", "READY"].includes(key)) {
    return { title: "정상 운영", tone: "success" };
  }
  if (["DEGRADED", "WARNING", "PAUSED"].includes(key)) {
    return { title: "일부 확인 필요", tone: "warning" };
  }
  if (["DOWN", "ERROR", "FAILED", "CRITICAL", "BLOCKED"].includes(key)) {
    return { title: "오류", tone: "error" };
  }
  if (["STOPPED", "OFF", "INACTIVE"].includes(key)) {
    return { title: "자동매매 중지", tone: "default" };
  }
  return { title: m.labelKo || "확인 필요", tone: m.tone };
}

export const KOREAN_STATUS_MAPPING_COUNT =
  Object.keys(STATUS_LABEL_MAP).length + Object.keys(BLOCKER_LABEL_MAP).length;
