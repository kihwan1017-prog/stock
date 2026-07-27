"use client";

import { Button, Result } from "antd";
import Link from "next/link";

import { authRoutes, userRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { canAccessAdminPortal } from "@/features/auth/utils/roles";
import { adminRoutes } from "@/config/routes";

export default function ForbiddenPage() {
  const { user, authenticated } = useAuth();
  const home =
    authenticated && canAccessAdminPortal(user?.roles)
      ? adminRoutes.dashboard
      : authenticated
        ? userRoutes.dashboard
        : authRoutes.login;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <Result
        status="403"
        title="접근 권한이 없습니다"
        subTitle="이 페이지는 현재 계정 권한으로 볼 수 없습니다. 관리자 화면은 관리자 권한이 필요합니다."
        extra={
          <Link href={home}>
            <Button type="primary">돌아가기</Button>
          </Link>
        }
      />
    </div>
  );
}
