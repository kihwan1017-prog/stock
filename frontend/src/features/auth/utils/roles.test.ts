import { describe, expect, it } from "vitest";

import {
  canAccessAdminPortal,
  displayRoleLabel,
  isTraderRole,
  requiredRolesForUserPath,
  resolvePostLoginPath,
} from "./roles";

describe("roles RBAC helpers", () => {
  it("trader 티어는 operator·trader·admin", () => {
    expect(isTraderRole(["viewer"])).toBe(false);
    expect(isTraderRole(["operator"])).toBe(true);
    expect(isTraderRole(["trader"])).toBe(true);
    expect(isTraderRole(["admin"])).toBe(true);
  });

  it("Admin 포털은 admin·operator만", () => {
    expect(canAccessAdminPortal(["viewer"])).toBe(false);
    expect(canAccessAdminPortal(["operator"])).toBe(true);
    expect(canAccessAdminPortal(["admin"])).toBe(true);
  });

  it("operator 표시명은 trader (operator)", () => {
    expect(displayRoleLabel("operator")).toBe("trader (operator)");
  });

  it("매매 경로는 trader 역할 요구", () => {
    expect(requiredRolesForUserPath("/user/dashboard")).toBeUndefined();
    expect(requiredRolesForUserPath("/user/trading")).toEqual([
      "admin",
      "operator",
      "trader",
    ]);
  });

  it("viewer의 admin next는 user dashboard로", () => {
    expect(
      resolvePostLoginPath({ roles: ["viewer"] }, "/admin/dashboard"),
    ).toBe("/user/dashboard");
    expect(
      resolvePostLoginPath({ roles: ["admin"] }, "/admin/members"),
    ).toBe("/admin/members");
  });
});
