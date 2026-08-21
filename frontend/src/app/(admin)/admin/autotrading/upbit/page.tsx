import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** Workspace canonical → 기존 Upbit autotrading page */
export default function AdminAutotradingUpbitRedirectPage() {
  redirect(adminRoutes.upbitAutotrading);
}
