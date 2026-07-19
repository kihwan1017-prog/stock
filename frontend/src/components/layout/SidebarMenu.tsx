"use client";

import { useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu } from "antd";
import type { MenuProps } from "antd";

import type { AppMenuItem } from "@/config/menu";
import { adminMenuItems } from "@/config/menu";
import { useLayoutStore } from "@/stores/layoutStore";

interface SidebarMenuProps {
  items?: AppMenuItem[];
}

export function SidebarMenu({ items = adminMenuItems }: SidebarMenuProps) {
  const pathname = usePathname();
  const router = useRouter();
  const setMobileMenuOpen = useLayoutStore((state) => state.setMobileMenuOpen);

  const menuItems: MenuProps["items"] = useMemo(
    () =>
      items
        .filter((item) => item.enabled)
        .map((item) => ({
          key: item.path,
          icon: item.icon,
          label: item.label,
        })),
    [items],
  );

  const selectedKeys = useMemo(() => {
    const matched = items.find(
      (item) => pathname === item.path || pathname.startsWith(`${item.path}/`),
    );
    return matched ? [matched.path] : [];
  }, [items, pathname]);

  return (
    <Menu
      mode="inline"
      selectedKeys={selectedKeys}
      items={menuItems}
      onClick={({ key }) => {
        router.push(key);
        setMobileMenuOpen(false);
      }}
      style={{ borderInlineEnd: "none" }}
    />
  );
}
