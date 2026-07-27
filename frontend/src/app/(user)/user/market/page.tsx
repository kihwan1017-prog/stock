import { redirect } from "next/navigation";

import { userRoutes } from "@/config/routes";

/** 구 경로 호환 → 주식 시장정보 (STEP4-6: /user/market → /user/markets/stocks) */
export default function UserMarketRedirectPage() {
  redirect(userRoutes.marketsStocks);
}
