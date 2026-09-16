/**
 * ACCOUNT-scope Live Trading Transition 페이로드 빌더.
 * BROKER scope는 UI에서 제공하지 않는다. Production 호출은 이 모듈이 하지 않는다.
 */

export const LIVE_TRANSITION_ACCOUNT_SCOPE = "ACCOUNT" as const;

export const APPROVAL_PHRASE_BY_BROKER = {
  KIWOOM: "ENABLE KIWOOM LIVE TRADING",
  UPBIT: "ENABLE UPBIT LIVE TRADING",
} as const;

export const DEFAULT_ACTIVATION_TTL_HOURS = 1;

export type LiveControlBrokerCode = keyof typeof APPROVAL_PHRASE_BY_BROKER;

export type AccountActivationPayload = {
  max_order_amount: number;
  max_daily_loss: number;
  paper_validation_approved: boolean;
  scope: typeof LIVE_TRANSITION_ACCOUNT_SCOPE;
  broker_code: LiveControlBrokerCode;
  user_broker_account_id: number;
};

export type AccountActivationRequestPayload = AccountActivationPayload & {
  requested_by: string;
};

export type AccountActivationApprovePayload = {
  approved_by: string;
  approval_phrase: string;
  reason?: string;
  ttl_hours: number;
  scope: typeof LIVE_TRANSITION_ACCOUNT_SCOPE;
  broker_code: LiveControlBrokerCode;
  user_broker_account_id: number;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function normalizeLiveControlBroker(
  brokerCode: unknown,
): LiveControlBrokerCode | null {
  const code = String(brokerCode ?? "").trim().toUpperCase();
  if (code === "KIWOOM" || code === "UPBIT") {
    return code;
  }
  return null;
}

/** broker별 승인 문구. 미지원 broker는 null (UI에서 승인 버튼 비활성). */
export function approvalPhraseForBroker(brokerCode: unknown): string | null {
  const code = normalizeLiveControlBroker(brokerCode);
  if (!code) return null;
  return APPROVAL_PHRASE_BY_BROKER[code];
}

function positiveAmount(value: unknown, fallback: number): number {
  const n = Number(value);
  if (Number.isFinite(n) && n > 0) return n;
  return fallback;
}

/**
 * ACCOUNT scope 고정 검증/요청 바디.
 * BROKER scope 또는 잘못된 UBA는 만들지 않는다.
 */
export function buildAccountActivationPayload(args: {
  brokerCode: unknown;
  userBrokerAccountId: unknown;
  maxOrderAmount?: unknown;
  maxDailyLoss?: unknown;
  paperValidationApproved?: boolean;
}): AccountActivationPayload | null {
  const broker = normalizeLiveControlBroker(args.brokerCode);
  const ubaId = Number(args.userBrokerAccountId);
  if (!broker || !Number.isInteger(ubaId) || ubaId < 1) {
    return null;
  }
  return {
    max_order_amount: positiveAmount(args.maxOrderAmount, 5000),
    max_daily_loss: positiveAmount(args.maxDailyLoss, 5000),
    paper_validation_approved: Boolean(args.paperValidationApproved),
    scope: LIVE_TRANSITION_ACCOUNT_SCOPE,
    broker_code: broker,
    user_broker_account_id: ubaId,
  };
}

export function buildAccountActivationRequestPayload(args: {
  brokerCode: unknown;
  userBrokerAccountId: unknown;
  requestedBy: string;
  maxOrderAmount?: unknown;
  maxDailyLoss?: unknown;
  paperValidationApproved?: boolean;
}): AccountActivationRequestPayload | null {
  const base = buildAccountActivationPayload(args);
  const requestedBy = String(args.requestedBy ?? "").trim();
  if (!base || !requestedBy) return null;
  return { ...base, requested_by: requestedBy };
}

export function buildAccountActivationApprovePayload(args: {
  brokerCode: unknown;
  userBrokerAccountId: unknown;
  approvedBy: string;
  approvalPhrase: string;
  reason?: string;
}): AccountActivationApprovePayload | null {
  const broker = normalizeLiveControlBroker(args.brokerCode);
  const ubaId = Number(args.userBrokerAccountId);
  const approvedBy = String(args.approvedBy ?? "").trim();
  const phrase = String(args.approvalPhrase ?? "");
  const expected = approvalPhraseForBroker(broker);
  if (!broker || !Number.isInteger(ubaId) || ubaId < 1) return null;
  if (!approvedBy || !expected) return null;
  if (phrase !== expected) return null;
  return {
    approved_by: approvedBy,
    approval_phrase: phrase,
    reason: args.reason,
    ttl_hours: DEFAULT_ACTIVATION_TTL_HOURS,
    scope: LIVE_TRANSITION_ACCOUNT_SCOPE,
    broker_code: broker,
    user_broker_account_id: ubaId,
  };
}

export function isValidateReady(result: unknown): boolean {
  const record = asRecord(result);
  if (!record) return false;
  return record.ready === true;
}

export function extractTransitionId(result: unknown): number | null {
  const record = asRecord(result);
  if (!record) return null;
  const id = Number(
    record.live_trading_transition_id ??
      record.transition_id ??
      record.id,
  );
  if (!Number.isInteger(id) || id < 1) return null;
  return id;
}

/** history/active 항목이 해당 UBA ACCOUNT Activation ACTIVE 인지 */
export function isAccountActivationActiveForUba(
  item: unknown,
  ubaId: number,
  brokerCode?: unknown,
): boolean {
  const record = asRecord(item);
  if (!record) return false;
  if (record.enabled !== true) return false;
  if (record.disabled_at) return false;
  const status = String(record.activation_status ?? "").toUpperCase();
  if (status && status !== "ACTIVE" && status !== "APPROVED") {
    // enabled=true 이고 만료 전인 레거시 행도 ACTIVE로 본다
    if (status !== "") return false;
  }
  const scope = String(record.scope ?? "").toUpperCase();
  if (scope !== LIVE_TRANSITION_ACCOUNT_SCOPE) return false;
  const itemUba = Number(record.user_broker_account_id);
  if (itemUba !== ubaId) return false;
  const expectedBroker = normalizeLiveControlBroker(brokerCode);
  if (expectedBroker) {
    const itemBroker = String(record.broker_code ?? "").toUpperCase();
    if (itemBroker && itemBroker !== expectedBroker) return false;
  }
  return true;
}

export function findActiveAccountActivation(
  historyOrActive: unknown,
  ubaId: number,
  brokerCode?: unknown,
): Record<string, unknown> | null {
  const record = asRecord(historyOrActive);
  const items: unknown[] = Array.isArray(historyOrActive)
    ? historyOrActive
    : Array.isArray(record?.items)
      ? (record?.items as unknown[])
      : record
        ? [record]
        : [];
  for (const item of items) {
    if (isAccountActivationActiveForUba(item, ubaId, brokerCode)) {
      return asRecord(item);
    }
  }
  return null;
}

/** Activation 잔여 TTL(초). ARM 요청 시 세션 상한으로 전달한다. */
export function remainingActivationSeconds(
  item: Record<string, unknown> | null | undefined,
  nowMs: number = Date.now(),
): number | null {
  if (!item) return null;
  const direct = Number(item.remaining_ttl_seconds);
  if (Number.isFinite(direct) && direct > 0) {
    return Math.floor(direct);
  }
  const expiresRaw = item.expires_at;
  if (typeof expiresRaw === "string" && expiresRaw.trim()) {
    const expMs = Date.parse(expiresRaw);
    if (Number.isFinite(expMs)) {
      const remaining = Math.floor((expMs - nowMs) / 1000);
      if (remaining > 0) return remaining;
    }
  }
  return null;
}

export function kiwoomExecutionBadges(args: {
  credentialVerified: boolean;
  sharedMarketMock: boolean;
}): { execution: "REAL" | "UNKNOWN"; sharedMarket: "MOCK" | "REAL" } {
  return {
    execution: args.credentialVerified ? "REAL" : "UNKNOWN",
    sharedMarket: args.sharedMarketMock ? "MOCK" : "REAL",
  };
}
