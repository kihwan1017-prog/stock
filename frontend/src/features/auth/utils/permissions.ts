import type { AuthUser } from "@/features/auth/types/auth";
import { isAdminRole, normalizeRoles } from "@/features/auth/utils/roles";

/** admin은 모든 권한 보유로 간주 */
export function hasPermission(
  user: AuthUser | null | undefined,
  ...codes: string[]
): boolean {
  if (!user || !codes.length) {
    return false;
  }
  if (isAdminRole(user.roles)) {
    return true;
  }
  const owned = new Set(user.permissions ?? []);
  return codes.every((code) => owned.has(code));
}

export function hasAnyPermission(
  user: AuthUser | null | undefined,
  ...codes: string[]
): boolean {
  if (!user || !codes.length) {
    return false;
  }
  if (isAdminRole(user.roles)) {
    return true;
  }
  const owned = new Set(user.permissions ?? []);
  return codes.some((code) => owned.has(code));
}

export function hasAnyRole(
  user: AuthUser | null | undefined,
  ...roles: string[]
): boolean {
  if (!user || !roles.length) {
    return false;
  }
  const owned = new Set(normalizeRoles(user.roles));
  return roles.some((role) => owned.has(normalizeRoles([role])[0] ?? role));
}
