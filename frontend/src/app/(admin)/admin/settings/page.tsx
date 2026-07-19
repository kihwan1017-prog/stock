import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** 구 경로 호환 → 환경설정 */
export default function AdminSettingsRedirectPage() {
  redirect(adminRoutes.envSettings);
}
