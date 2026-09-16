import { describe, expect, it } from "vitest";

import {
  canAccessAdminPortal,
  displayRoleLabel,
  hasValidAppRole,
  isAdminRole,
  normalizeRoles,
  requiredRolesForUserPath,
  resolvePostLoginPath,
  roleHomePath,
} from "./roles";

describe("roles RBAC helpers (ADMIN / USER)", () => {
  it("레거시 viewer·operator·trader를 admin/user로 정규화", () => {
    expect(normalizeRoles(["viewer"])).toEqual(["user"]);
    expect(normalizeRoles(["operator"])).toEqual(["admin"]);
    expect(normalizeRoles(["trader", "user"])).toEqual(["user"]);
  });

  it("Admin 포털은 admin만 (operator 레거시는 admin으로 매핑)", () => {
    expect(canAccessAdminPortal(["user"])).toBe(false);
    expect(canAccessAdminPortal(["viewer"])).toBe(false);
    expect(canAccessAdminPortal(["admin"])).toBe(true);
    expect(canAccessAdminPortal(["operator"])).toBe(true);
  });

  it("표시명은 admin / user", () => {
    expect(displayRoleLabel("admin")).toBe("admin");
    expect(displayRoleLabel("user")).toBe("user");
    expect(displayRoleLabel("viewer")).toBe("user");
    expect(displayRoleLabel("operator")).toBe("admin");
  });

  it("매매·전략 경로는 USER도 접근 가능", () => {
    expect(requiredRolesForUserPath("/user/dashboard")).toBeUndefined();
    expect(requiredRolesForUserPath("/user/trading")).toBeUndefined();
    expect(requiredRolesForUserPath("/user/strategies")).toBeUndefined();
  });

  it("USER의 admin next는 forbidden, ADMIN은 유지", () => {
    expect(
      resolvePostLoginPath({ roles: ["user"] }, "/admin/dashboard"),
    ).toBe("/forbidden");
    expect(
      resolvePostLoginPath({ roles: ["viewer"] }, "/admin/dashboard"),
    ).toBe("/forbidden");
    expect(
      resolvePostLoginPath({ roles: ["admin"] }, "/admin/members"),
    ).toBe("/admin/members");
  });

  it("isAdminRole은 admin만 true", () => {
    expect(isAdminRole(["admin"])).toBe(true);
    expect(isAdminRole(["user"])).toBe(false);
  });

  it("Role별 홈은 ADMIN→/admin/dashboard, USER→forbidden (single operator)", () => {
    expect(roleHomePath(["user"])).toBe("/forbidden");
    expect(roleHomePath(["admin"])).toBe("/admin/dashboard");
    expect(resolvePostLoginPath({ roles: ["user"] })).toBe("/forbidden");
    expect(resolvePostLoginPath({ roles: ["admin"] })).toBe(
      "/admin/dashboard",
    );
  });

  it("비밀번호 변경·온보딩이 Role 홈보다 우선", () => {
    expect(
      resolvePostLoginPath({
        roles: ["admin"],
        passwordChangeRequired: true,
      }),
    ).toBe("/change-password");
    expect(
      resolvePostLoginPath({
        roles: ["user"],
        onboardingCompleted: false,
      }),
    ).toBe("/onboarding");
  });

  it("defaultRoute는 권한에 맞게만 허용", () => {
    expect(
      resolvePostLoginPath({
        roles: ["user"],
        defaultRoute: "/admin/dashboard",
      }),
    ).toBe("/forbidden");
    expect(
      resolvePostLoginPath({
        roles: ["admin"],
        defaultRoute: "/admin/dashboard",
      }),
    ).toBe("/admin/dashboard");
  });

  it("유효하지 않은 Role·로그인 루프 next는 차단", () => {
    expect(hasValidAppRole([])).toBe(false);
    expect(hasValidAppRole(["guest"])).toBe(false);
    expect(resolvePostLoginPath({ roles: [] })).toBe("/forbidden");
    expect(resolvePostLoginPath({ roles: ["guest"] })).toBe("/forbidden");
    expect(resolvePostLoginPath({ roles: ["user"] }, "/login")).toBe(
      "/forbidden",
    );
  });
});
