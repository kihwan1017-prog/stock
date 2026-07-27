"use client";

import { adminRoutes } from "@/config/routes";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { ProfileWorkspace } from "@/features/user/profile/ProfileWorkspace";

/** 관리자 본인 정보 — /api/v1/user/profile 등 self API 재사용 */
export default function AdminProfilePage() {
  return (
    <ProfileWorkspace
      Shell={AdminPageShell}
      homeHref={adminRoutes.dashboard}
      homeLabel="Admin"
      title="관리자 내 정보"
    />
  );
}
