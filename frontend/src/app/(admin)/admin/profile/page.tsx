import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** Single-admin: 내 정보 메뉴 제거 */
export default function AdminProfileRedirectPage() {
  redirect(adminRoutes.dashboard);
}
