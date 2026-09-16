import { redirect } from "next/navigation";

import { userRoutes } from "@/config/routes";

/** 전략 그룹 하위 자동매매 별칭 → 기존 자동매매 화면 */
export default function UserStrategiesAutoRedirectPage() {
  redirect(userRoutes.autoTrading);
}
