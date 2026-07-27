/**
 * 모의계좌 수정 UI 헬퍼.
 * DB에 없는 설명/전략/위험 필드는 다루지 않는다.
 */

export interface PaperAccountRecord {
  account_id: number;
  user_id?: number | null;
  account_name: string;
  currency_code?: string;
  initial_cash: number | string;
  available_cash?: number | string;
  realized_profit_loss?: number | string;
  is_default?: boolean;
  is_active?: boolean;
  has_trading_history?: boolean;
  can_edit_initial_cash?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface PaperAccountUpdateRequest {
  account_name?: string;
  is_active?: boolean;
  is_default?: boolean;
  initial_cash?: number;
}

export function canShowPaperAccountEditButton(
  canWrite: boolean,
  accountId: unknown,
): boolean {
  if (!canWrite) return false;
  const id = Number(accountId);
  return Number.isFinite(id) && id > 0;
}

export function resolveCanEditInitialCash(
  account: Pick<
    PaperAccountRecord,
    "can_edit_initial_cash" | "has_trading_history"
  >,
): boolean {
  if (typeof account.can_edit_initial_cash === "boolean") {
    return account.can_edit_initial_cash;
  }
  return account.has_trading_history !== true;
}

export function initialCashDisabledReason(
  canEdit: boolean,
): string | null {
  if (canEdit) return null;
  return "주문·체결·보유 이력이 있어 초기 자산을 수정할 수 없습니다.";
}

/** 폼 → PATCH body. 변경된 필드만 포함. */
export function buildPaperAccountUpdatePayload(
  original: PaperAccountRecord,
  values: {
    account_name: string;
    is_active: boolean;
    is_default: boolean;
    initial_cash: number;
  },
): PaperAccountUpdateRequest {
  const payload: PaperAccountUpdateRequest = {};
  const name = values.account_name.trim();
  if (name !== (original.account_name ?? "").trim()) {
    payload.account_name = name;
  }
  if (Boolean(values.is_active) !== Boolean(original.is_active)) {
    payload.is_active = values.is_active;
  }
  if (Boolean(values.is_default) !== Boolean(original.is_default)) {
    payload.is_default = values.is_default;
  }
  const canEditCash = resolveCanEditInitialCash(original);
  const originalCash = Number(original.initial_cash);
  if (
    canEditCash &&
    Number.isFinite(values.initial_cash) &&
    values.initial_cash !== originalCash
  ) {
    payload.initial_cash = values.initial_cash;
  }
  return payload;
}

export function validatePaperAccountUpdateForm(values: {
  account_name?: string;
  initial_cash?: number;
  canEditInitialCash: boolean;
}): string | null {
  const name = (values.account_name ?? "").trim();
  if (!name) {
    return "계좌명을 입력하세요.";
  }
  if (name.length > 100) {
    return "계좌명은 최대 100자입니다.";
  }
  if (values.canEditInitialCash) {
    const cash = Number(values.initial_cash);
    if (!Number.isFinite(cash) || cash <= 0) {
      return "초기 자산은 0보다 커야 합니다.";
    }
  }
  return null;
}
