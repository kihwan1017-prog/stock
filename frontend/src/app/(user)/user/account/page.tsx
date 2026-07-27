import { redirect } from "next/navigation";

import { userRoutes } from "@/config/routes";

/** 구 경로 호환 → 전체 계좌 (STEP4-6: /user/account → /user/accounts) */
export default function UserAccountRedirectPage() {
  redirect(userRoutes.accounts);
}
