import { redirect } from "next/navigation";

import { userRoutes } from "@/config/routes";

/** 구 경로 호환 → 내 주문·체결 (STEP4-6: /user/trades → /user/orders) */
export default function UserTradesRedirectPage() {
  redirect(userRoutes.orders);
}
