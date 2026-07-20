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

export function SidebarMenu({ items = adminMenuItems }: SidebarMenuProps) {
  const pathname = usePathname();
  const router = useRouter();
  const setMobileMenuOpen = useLayoutStore((state) => state.setMobileMenuOpen);

  const menuItems = useMemo(() => toAntdItems(items), [items]);
  const flat = useMemo(() => flattenMenuItems(items), [items]);

  const selectedKeys = useMemo(() => {
    const matches = flat.filter(
      (item) =>
        item.path &&
        (pathname === item.path || pathname.startsWith(`${item.path}/`)),
    );
    if (!matches.length) {
      return [];
    }
    // 가장 긴 path 일치 우선 (중첩 경로), 동일 path면 모두 선택
    const maxLen = Math.max(...matches.map((item) => item.path!.length));
    return matches
      .filter((item) => item.path!.length === maxLen)
      .map((item) => item.key);
  }, [flat, pathname]);

  const openKeys = useMemo(() => {
    const keys: string[] = [];
    for (const group of items) {
      if (!group.children?.length) continue;
      const hit = group.children.some(
        (child) =>
          child.path &&
          (pathname === child.path || pathname.startsWith(`${child.path}/`)),
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
