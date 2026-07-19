"use client";

import { Breadcrumb } from "antd";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { PageContainer } from "@/components/common/PageContainer";
import { getRouteTitle, userRoutes } from "@/config/routes";

interface UserPageShellProps {
  title: string;
  description?: string;
  extra?: ReactNode;
  children: ReactNode;
}

/** AdminPageShell과 동일한 Breadcrumb + PageContainer 패턴 */
export function UserPageShell({
  title,
  description,
  extra,
  children,
}: UserPageShellProps) {
  const pathname = usePathname();

  return (
    <PageContainer title={title} description={description} extra={extra}>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link href={userRoutes.dashboard}>User</Link> },
          { title: getRouteTitle(pathname) || title },
        ]}
      />
      {children}
    </PageContainer>
  );
}
