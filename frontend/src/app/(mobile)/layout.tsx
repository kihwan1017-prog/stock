"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { RegisterMobileServiceWorker } from "@/features/mobile/RegisterMobileServiceWorker";

import styles from "./mobile-shell.module.css";

const NAV = [
  { href: "/mobile", label: "홈", match: (p: string) => p === "/mobile" },
  {
    href: "/mobile/autotrading",
    label: "자동매매",
    match: (p: string) => p.startsWith("/mobile/autotrading"),
  },
  {
    href: "/mobile/orders",
    label: "주문",
    match: (p: string) => p.startsWith("/mobile/orders"),
  },
  {
    href: "/mobile/positions",
    label: "성과",
    match: (p: string) => p.startsWith("/mobile/positions"),
  },
  {
    href: "/mobile/alerts",
    label: "설정",
    match: (p: string) => p.startsWith("/mobile/alerts"),
  },
] as const;

export default function MobileLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/mobile";

  return (
    <AuthGuard requiredRoles={["admin"]}>
      <RegisterMobileServiceWorker />
      <div className={styles.shell}>
        <main className={styles.main}>{children}</main>
        <nav className={styles.nav} aria-label="모바일 하단 메뉴">
          {NAV.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={active ? styles.navItemActive : styles.navItem}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </AuthGuard>
  );
}
