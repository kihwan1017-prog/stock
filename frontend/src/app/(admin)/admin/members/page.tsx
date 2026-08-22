import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** Single-admin: 회원 UI 메뉴 제거 — 내부 identity API는 유지 */
export default function AdminMembersRedirectPage() {
  redirect(adminRoutes.dashboard);
}
