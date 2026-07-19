import { adminRoutes, userRoutes } from "@/config/routes";
import type { AuthUser } from "@/features/auth/types/auth";

/** Backend 시드 역할 */
export const ROLE_ADMIN = "admin";
export const ROLE_OPERATOR = "operator";
export const ROLE_VIEWER = "viewer";

/**
 * 제품 스펙의 trader — Backend에는 operator로 시드됨.
 * JWT에 trader가 오면 동일 티어로 인정 (향후 시드 대비).
 */
export const ROLE_TRADER_ALIASES = [ROLE_OPERATOR, "trader"] as const;

export type ProductRole = "viewer" | "trader" | "admin";

export function normalizeRoles(roles: string[] | undefined | null): string[] {
  return (roles ?? []).map((role) => role.trim().toLowerCase()).filter(Boolean);
}

export function isAdminRole(roles: string[] | undefined | null): boolean {
  return normalizeRoles(roles).includes(ROLE_ADMIN);
}

/** trader 티어: operator | trader | admin */
export function isTraderRole(roles: string[] | undefined | null): boolean {
  const normalized = normalizeRoles(roles);
  if (normalized.includes(ROLE_ADMIN)) return true;
  return ROLE_TRADER_ALIASES.some((code) => normalized.includes(code));
}

/** Admin 콘솔 진입: admin | operator (viewer 제외) */
export function canAccessAdminPortal(
  roles: string[] | undefined | null,
): boolean {
  const normalized = normalizeRoles(roles);
  return (
    normalized.includes(ROLE_ADMIN) || normalized.includes(ROLE_OPERATOR)
  );
}

/** UI 표시용 — operator는 trader로 표기 */
export function displayRoleLabel(roleCode: string): string {
  const code = roleCode.trim().toLowerCase();
  if (code === ROLE_OPERATOR) return "trader (operator)";
  if (code === "trader") return "trader";
  if (code === ROLE_ADMIN) return "admin";
  if (code === ROLE_VIEWER) return "viewer";
  return roleCode;
}

/** 뱃지용 주 역할 */
export function primaryProductRole(
  roles: string[] | undefined | null,
): ProductRole {
  if (isAdminRole(roles)) return "admin";
  if (isTraderRole(roles)) return "trader";
  return "viewer";
}

/**
 * User 메뉴 최소 접근 티어.
 * viewer < trader < admin
 */
export type UserMenuAccess = "viewer" | "trader" | "admin";

export function meetsUserMenuAccess(
  roles: string[] | undefined | null,
  minAccess: UserMenuAccess = "viewer",
): boolean {
  if (minAccess === "viewer") return true;
  if (minAccess === "trader") return isTraderRole(roles);
  return isAdminRole(roles);
}

/** 매매·자동매매·전략 실행 등 trader 이상 경로 */
const TRADER_USER_PATH_PREFIXES = [
  userRoutes.trading,
  userRoutes.autoTrading,
  userRoutes.strategies,
  userRoutes.backtests,
];

export function requiredRolesForUserPath(
  pathname: string,
): string[] | undefined {
  const needsTrader = TRADER_USER_PATH_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  if (!needsTrader) return undefined;
  return [ROLE_ADMIN, ROLE_OPERATOR, "trader"];
}

/**
 * 로그인 후 이동 경로.
 * viewer가 Admin URL을 요청하면 User 대시보드로 보낸다.
 */
export function resolvePostLoginPath(
  user: Pick<AuthUser, "roles">,
  requestedPath?: string | null,
): string {
  const path =
    requestedPath && requestedPath.startsWith("/") ? requestedPath : null;
  const wantsAdmin = Boolean(path?.startsWith("/admin"));

  if (wantsAdmin && !canAccessAdminPortal(user.roles)) {
    return userRoutes.dashboard;
  }
  if (path) return path;
  return canAccessAdminPortal(user.roles)
    ? adminRoutes.dashboard
    : userRoutes.dashboard;
}
