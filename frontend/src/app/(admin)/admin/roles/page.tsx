import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** Single-admin: 권한 UI 메뉴 제거 */
export default function AdminRolesRedirectPage() {
  redirect(adminRoutes.dashboard);
}
