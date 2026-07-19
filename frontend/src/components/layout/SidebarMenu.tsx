"use client";

import { useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu } from "antd";
import type { MenuProps } from "antd";

import { appMenuItems } from "@/config/menu";
import { useLayoutStore } from "@/stores/layoutStore";

export function SidebarMenu() {
  const pathname = usePathname();
  const router = useRouter();
  const setMobileMenuOpen = useLayoutStore((state) => state.setMobileMenuOpen);

  const items: MenuProps["items"] = useMemo(
    () =>
      appMenuItems
        .filter((item) => item.enabled)
        .map((item) => ({
          key: item.path,
          icon: item.icon,
          label: item.label,
        })),
    [],
  );

  const selectedKeys = useMemo(() => {
    const matched = appMenuItems.find(
      (item) => pathname === item.path || pathname.startsWith(`${item.path}/`),
    );
    return matched ? [matched.path] : [];
  }, [pathname]);

  return (
    <Menu
      mode="inline"
      selectedKeys={selectedKeys}
      items={items}
      onClick={({ key }) => {
        router.push(key);
        setMobileMenuOpen(false);
      }}
      style={{ borderInlineEnd: "none" }}
    />
  );
}
