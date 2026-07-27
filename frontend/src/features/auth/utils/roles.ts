import { adminRoutes, authRoutes, userRoutes } from "@/config/routes";
import type { AuthUser } from "@/features/auth/types/auth";

/** Backend 시드 역할 — ADMIN / USER 두 개만 */
export const ROLE_ADMIN = "admin";
export const ROLE_USER = "user";

/** 레거시 Role → 정식 코드 */
const ROLE_ALIASES: Record<string, string> = {
  viewer: ROLE_USER,
  operator: ROLE_ADMIN,
  trader: ROLE_USER,
};

export type ProductRole = "user" | "admin";

export function normalizeRoleCode(role: string): string {
  const cleaned = role.trim().toLowerCase();
  return ROLE_ALIASES[cleaned] ?? cleaned;
}

export function normalizeRoles(roles: string[] | undefined | null): string[] {
  const unique: string[] = [];
  for (const role of roles ?? []) {
    const normalized = normalizeRoleCode(role);
    if (normalized && !unique.includes(normalized)) {
      unique.push(normalized);
    }
  }
  return unique;
}

export function isAdminRole(roles: string[] | undefined | null): boolean {
  return normalizeRoles(roles).includes(ROLE_ADMIN);
}

/** @deprecated STEP2 — admin/user만 사용. admin이면 true */
export function isTraderRole(roles: string[] | undefined | null): boolean {
  return isAdminRole(roles);
}

/** Admin 콘솔 진입: admin만 */
export function canAccessAdminPortal(
  roles: string[] | undefined | null,
): boolean {
  return isAdminRole(roles);
}

/** ADMIN 또는 USER 중 하나라도 있으면 True */
export function hasValidAppRole(
  roles: string[] | undefined | null,
): boolean {
  const normalized = normalizeRoles(roles);
  return (
    normalized.includes(ROLE_ADMIN) || normalized.includes(ROLE_USER)
  );
}

/** Role별 홈 대시보드 */
export function roleHomePath(roles: string[] | undefined | null): string {
  return canAccessAdminPortal(roles)
    ? adminRoutes.dashboard
    : userRoutes.dashboard;
}

/** UI 표시용 */
export function displayRoleLabel(roleCode: string): string {
  const code = normalizeRoleCode(roleCode);
  if (code === ROLE_ADMIN) return "admin";
  if (code === ROLE_USER) return "user";
  return roleCode;
}

/** 뱃지용 주 역할 */
export function primaryProductRole(
  roles: string[] | undefined | null,
): ProductRole {
  return isAdminRole(roles) ? "admin" : "user";
}

/**
 * User 메뉴 최소 접근 티어.
 * user < admin
 */
export type UserMenuAccess = "user" | "admin";

export function meetsUserMenuAccess(
  roles: string[] | undefined | null,
  minAccess: UserMenuAccess = "user",
): boolean {
  if (minAccess === "user") return true;
  return isAdminRole(roles);
}

/**
 * User 경로 역할 게이트.
 * 본인 매매·전략은 USER도 접근 가능 — 경로 단위 역할 제한 없음.
 * 화면 내부 admin 전용 액션은 canAccessAdminPortal로 게이팅.
 */
const ADMIN_ONLY_USER_PATH_PREFIXES: string[] = [];

export function requiredRolesForUserPath(
  pathname: string,
): string[] | undefined {
  const needsAdmin = ADMIN_ONLY_USER_PATH_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  if (!needsAdmin) return undefined;
  return [ROLE_ADMIN];
}

const AUTH_LOOP_PATHS = new Set([
  authRoutes.login,
  authRoutes.signup,
  "/login",
  "/signup",
]);

function isSafeInternalPath(path: string | null | undefined): path is string {
  return Boolean(path && path.startsWith("/") && !path.startsWith("//"));
}

/**
 * 로그인 후 이동 경로.
 * 우선순위: 비밀번호 변경 → 온보딩 → next(권한 검증) → defaultRoute(권한 검증) → Role 홈
 */
export function resolvePostLoginPath(
  user: Pick<
    AuthUser,
    "roles" | "defaultRoute" | "passwordChangeRequired" | "onboardingCompleted"
  >,
  requestedPath?: string | null,
): string {
  if (user.passwordChangeRequired) {
    return authRoutes.changePassword;
  }
  if (user.onboardingCompleted === false) {
    return authRoutes.onboarding;
  }

  if (!hasValidAppRole(user.roles)) {
    return authRoutes.forbidden;
  }

  const home = roleHomePath(user.roles);
  const path = isSafeInternalPath(requestedPath) ? requestedPath : null;

  if (path) {
    if (AUTH_LOOP_PATHS.has(path)) {
      return home;
    }
    if (path.startsWith("/admin") && !canAccessAdminPortal(user.roles)) {
      return authRoutes.forbidden;
    }
    return path;
  }

  if (isSafeInternalPath(user.defaultRoute)) {
    const defaultRoute = user.defaultRoute;
    if (AUTH_LOOP_PATHS.has(defaultRoute) || defaultRoute === "/forbidden") {
      return home;
    }
    if (
      defaultRoute.startsWith("/admin") &&
      !canAccessAdminPortal(user.roles)
    ) {
      return home;
    }
    return defaultRoute;
  }

  return home;
}
