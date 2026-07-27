import { describe, expect, it } from "vitest";

import {
  adminMenuItems,
  flattenMenuItems,
  userMenuItems,
} from "@/config/menu";
import {
  adminRoutes,
  type AdminRoute,
  type UserRoute,
  userRoutes,
} from "@/config/routes";

describe("menu link validity (STEP7)", () => {
  it("USER 메뉴의 모든 path는 userRoutes 값이어야 한다", () => {
    const allowed = new Set<UserRoute>(Object.values(userRoutes));
    const paths = flattenMenuItems(userMenuItems)
      .map((item) => item.path)
      .filter((path): path is UserRoute => path !== undefined);

    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      expect(allowed.has(path), `unknown user menu path: ${path}`).toBe(true);
      expect(path.startsWith("/user") || path.startsWith("/login")).toBe(true);
    }
  });

  it("ADMIN 메뉴의 모든 path는 adminRoutes 값이어야 한다", () => {
    const allowed = new Set<AdminRoute>(Object.values(adminRoutes));
    const paths = flattenMenuItems(adminMenuItems)
      .map((item) => item.path)
      .filter((path): path is AdminRoute => path !== undefined);

    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      expect(allowed.has(path), `unknown admin menu path: ${path}`).toBe(true);
      expect(path.startsWith("/admin") || path.startsWith("/login")).toBe(true);
    }
  });

  it("USER·ADMIN 메뉴가 서로 섞이지 않는다", () => {
    const userPaths = flattenMenuItems(userMenuItems).map((i) => i.path);
    const adminPaths = flattenMenuItems(adminMenuItems).map((i) => i.path);
    for (const path of userPaths) {
      if (!path) continue;
      expect(path.startsWith("/admin")).toBe(false);
    }
    for (const path of adminPaths) {
      if (!path) continue;
      expect(path.startsWith("/user")).toBe(false);
    }
  });
});
