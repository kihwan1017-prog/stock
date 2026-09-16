import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** 거래내역 → 주문·체결 (체결 탭) */
export default function AdminTradesRedirectPage() {
  redirect(`${adminRoutes.orders}?tab=fills`);
}
