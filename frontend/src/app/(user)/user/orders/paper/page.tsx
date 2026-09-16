import { redirect } from "next/navigation";

import { userRoutes } from "@/config/routes";

/** 「내 주문·체결」 메인 화면이 이미 Paper 계좌 전용이므로 그대로 연결 */
export default function UserOrdersPaperRedirectPage() {
  redirect(userRoutes.orders);
}
