"use client";

import { Breadcrumb } from "antd";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { PageContainer } from "@/components/common/PageContainer";
import { getRouteTitle } from "@/config/routes";

interface AdminPageShellProps {
  title: string;
  description?: string;
  extra?: ReactNode;
  children: ReactNode;
}

export function AdminPageShell({
  title,
  description,
  extra,
  children,
}: AdminPageShellProps) {
  const pathname = usePathname();

  return (
    <PageContainer
      title={title}
      description={description}
      extra={extra}
    >
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link href="/admin/dashboard">Admin</Link> },
          { title: getRouteTitle(pathname) || title },
        ]}
      />
      {children}
    </PageContainer>
  );
}
