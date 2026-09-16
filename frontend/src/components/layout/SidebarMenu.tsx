"use client";

import { useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu } from "antd";
import type { MenuProps } from "antd";

import type { AppMenuItem } from "@/config/menu";
import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { useLayoutStore } from "@/stores/layoutStore";

interface SidebarMenuProps {
  items?: AppMenuItem[];
}

function toAntdItems(items: AppMenuItem[]): MenuProps["items"] {
  return items
    .filter((item) => item.enabled)
    .map((item) => {
      if (item.children?.length) {
        return {
          key: item.key,
          icon: item.icon,
          label: item.label,
          children: toAntdItems(item.children),
        };
      }
      // path가 같아도 key는 고유해야 함 (예: monitoring / data → 동일 /admin/monitoring)
      return {
        key: item.key,
        icon: item.icon,
        label: item.label,
      };
    });
}

/** leaf path 또는 Workspace matchPaths로 현재 경로 매칭 */
function menuItemMatchesPath(item: AppMenuItem, pathname: string): boolean {
  const paths = [
    ...(item.path ? [item.path] : []),
    ...((item.matchPaths as readonly string[] | undefined) ?? []),
  ];
  for (const path of paths) {
    if (pathname === path) return true;
    // /admin/ai 는 하위 /admin/ai/* 를 먹지 않음
    if (path === "/admin/ai") continue;
    if (pathname.startsWith(`${path}/`)) return true;
  }
  return false;
}

function matchPathLength(item: AppMenuItem, pathname: string): number {
  const paths = [
    ...(item.path ? [item.path] : []),
    ...((item.matchPaths as readonly string[] | undefined) ?? []),
  ];
  let max = 0;
  for (const path of paths) {
    if (pathname === path) {
      max = Math.max(max, path.length);
      continue;
    }
    if (path === "/admin/ai") continue;
    if (pathname.startsWith(`${path}/`)) {
      max = Math.max(max, path.length);
    }
  }
  return max;
}

export function SidebarMenu({ items = adminMenuItems }: SidebarMenuProps) {
  const pathname = usePathname();
  const router = useRouter();
  const setMobileMenuOpen = useLayoutStore((state) => state.setMobileMenuOpen);

  const menuItems = useMemo(() => toAntdItems(items), [items]);
  const flat = useMemo(() => flattenMenuItems(items), [items]);

  const selectedKeys = useMemo(() => {
    const matches = flat.filter((item) => menuItemMatchesPath(item, pathname));
    if (!matches.length) {
      return [];
    }
    const maxLen = Math.max(
      ...matches.map((item) => matchPathLength(item, pathname)),
    );
    return matches
      .filter((item) => matchPathLength(item, pathname) === maxLen)
      .map((item) => item.key);
  }, [flat, pathname]);

  const openKeys = useMemo(() => {
    const keys: string[] = [];
    for (const group of items) {
      if (!group.children?.length) continue;
      const hit = group.children.some((child) =>
        menuItemMatchesPath(child, pathname),
      );
      if (hit) keys.push(group.key);
    }
    return keys;
  }, [items, pathname]);

  return (
    <Menu
      mode="inline"
      selectedKeys={selectedKeys}
      defaultOpenKeys={openKeys}
      items={menuItems}
      onClick={({ key }) => {
        const target = flat.find((item) => item.key === key);
        if (target?.path) {
          router.push(target.path);
          setMobileMenuOpen(false);
        }
      }}
      style={{ borderInlineEnd: "none" }}
    />
  );
}
