"use client";

import { redirect } from "next/navigation";

import { adminRoutes } from "@/config/routes";

/** STEP56: /admin/market → 모니터링 */
export default function AdminMarketPage() {
  redirect(adminRoutes.monitoring);
}
