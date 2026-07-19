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
      return {
        key: item.path ?? item.key,
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
    const matched = flat
      .filter((item) => item.path)
      .sort((a, b) => (b.path?.length ?? 0) - (a.path?.length ?? 0))
      .find(
        (item) =>
          pathname === item.path || pathname.startsWith(`${item.path}/`),
      );
    return matched?.path ? [matched.path] : [];
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
        if (key.startsWith("/")) {
          router.push(key);
          setMobileMenuOpen(false);
        }
      }}
      style={{ borderInlineEnd: "none" }}
    />
  );
}
