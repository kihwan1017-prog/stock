import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** Legacy alias → canonical /admin/autotrading/upbit */
export default function AdminUpbitAutotradingLegacyRedirectPage() {
  redirect(adminRoutes.autotradingUpbit);
}
