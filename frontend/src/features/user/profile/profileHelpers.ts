/** Profile UI 보안 헬퍼 — STEP73 */

export function maskEmailPreview(email: string): string {
  if (!email.includes("@")) return "***";
  const [local, domain] = email.split("@");
  if (!local) return `***@${domain}`;
  const visible = local.slice(0, Math.min(2, local.length));
  return `${visible}***@${domain}`;
}

const TOKEN_FIELD_RE = /(token|jwt|authorization|password_hash|secret)/i;

export function shouldHideTokenFromUi(fieldName: string): boolean {
  return TOKEN_FIELD_RE.test(fieldName);
}
