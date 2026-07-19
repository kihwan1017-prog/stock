import type { AuthUser } from "@/features/auth/types/auth";

/** admin은 모든 권한 보유로 간주 */
export function hasPermission(
  user: AuthUser | null | undefined,
  ...codes: string[]
): boolean {
  if (!user || !codes.length) {
    return false;
  }
  if (user.roles.includes("admin")) {
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
  if (user.roles.includes("admin")) {
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
  return roles.some((role) => user.roles.includes(role));
}
