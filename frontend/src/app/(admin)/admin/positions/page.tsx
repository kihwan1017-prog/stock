import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** 구 경로 호환 → 포트폴리오 */
export default function AdminPositionsRedirectPage() {
  redirect(adminRoutes.portfolio);
}
