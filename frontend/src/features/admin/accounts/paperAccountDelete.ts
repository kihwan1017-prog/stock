/**
 * 모의계좌 Soft Delete UI 헬퍼.
 * Hard Delete는 지원하지 않으며, 확인 모달 문구만 구성한다.
 */

export interface PaperAccountDeleteTarget {
  account_id: number;
  account_name?: string | null;
  is_default?: boolean;
}

export function buildPaperAccountDeleteConfirmContent(
  target: PaperAccountDeleteTarget,
): string {
  const name = (target.account_name ?? "").trim() || `(#${target.account_id})`;
  const defaultHint = target.is_default
    ? "\n\n이 계좌는 기본 계좌입니다. 삭제 후 기본 지정이 해제됩니다."
    : "";
  return (
    `모의계좌 "${name}" (ID: ${target.account_id}) 을(를) Soft Delete 할까요?\n\n` +
    "· 목록에서 숨겨지며 주문/체결 이력은 보존됩니다.\n" +
    "· Hard Delete(물리 삭제)는 수행하지 않습니다." +
    defaultHint
  );
}

export function canShowPaperAccountDeleteButton(
  isAdmin: boolean,
  accountId: unknown,
): boolean {
  if (!isAdmin) return false;
  const id = Number(accountId);
  return Number.isFinite(id) && id > 0;
}
