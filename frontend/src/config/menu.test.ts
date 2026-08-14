import { existsSync } from "node:fs";
import { join } from "node:path";
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

/** vitest cwd = frontend/ */
const frontendRoot = process.cwd();

function pageFileForRoute(route: string): string | null {
  if (route.startsWith("/admin/")) {
    return join(frontendRoot, "src/app/(admin)", route.slice(1), "page.tsx");
  }
  if (route.startsWith("/user/")) {
    return join(frontendRoot, "src/app/(user)", route.slice(1), "page.tsx");
  }
  return null;
}

function duplicatePaths(paths: Array<string | undefined>): string[] {
  const seen = new Set<string>();
  const duplicates: string[] = [];
  for (const path of paths) {
    if (!path) continue;
    if (seen.has(path)) {
      duplicates.push(path);
    }
    seen.add(path);
  }
  return duplicates;
}

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

  it("M3-A 사이드바 카운트: Admin 10/52, User 12/27", () => {
    expect(adminMenuItems).toHaveLength(10);
    expect(flattenMenuItems(adminMenuItems)).toHaveLength(52);
    expect(userMenuItems).toHaveLength(12);
    expect(flattenMenuItems(userMenuItems)).toHaveLength(27);
  });

  it("ADMIN·USER 사이드바에 동일 path가 중복 노출되지 않는다", () => {
    expect(duplicatePaths(flattenMenuItems(adminMenuItems).map((item) => item.path))).toEqual([]);
    expect(duplicatePaths(flattenMenuItems(userMenuItems).map((item) => item.path))).toEqual([]);
  });

  it("/admin/monitoring 사이드바 노출은 1회다", () => {
    const monitoringLeaves = flattenMenuItems(adminMenuItems).filter(
      (item) => item.path === adminRoutes.monitoring,
    );
    expect(monitoringLeaves).toHaveLength(1);
    expect(monitoringLeaves[0]?.key).toBe("system-monitoring");
  });

  it("사이드바 leaf path에 대응하는 page.tsx가 존재한다", () => {
    const leaves = [
      ...flattenMenuItems(adminMenuItems),
      ...flattenMenuItems(userMenuItems),
    ];
    const missing: string[] = [];
    for (const item of leaves) {
      if (!item.path) continue;
      const pageFile = pageFileForRoute(item.path);
      if (!pageFile || !existsSync(pageFile)) {
        missing.push(item.path);
      }
    }
    expect(missing).toEqual([]);
  });
});
