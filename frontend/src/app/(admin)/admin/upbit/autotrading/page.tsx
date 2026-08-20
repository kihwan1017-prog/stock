"use client";

import { Suspense, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Spin } from "antd";

import { adminRoutes } from "@/config/routes";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { UpbitAutotradingSettingsWorkspace } from "@/features/admin/upbit/UpbitAutotradingSettingsWorkspace";
import { DEFAULT_UPBIT_AUTOTRADING_UBA_ID } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";

function parseUbaId(raw: string | null): number {
  const n = Number(raw);
  if (Number.isFinite(n) && n > 0) return Math.trunc(n);
  return DEFAULT_UPBIT_AUTOTRADING_UBA_ID;
}

function UpbitAutotradingPageBody() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const ubaId = parseUbaId(searchParams.get("ubaId"));

  const onUbaIdChange = useCallback(
    (next: number) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("ubaId", String(next));
      router.replace(
        `${adminRoutes.upbitAutotrading}?${params.toString()}`,
      );
    },
    [router, searchParams],
  );

  return (
    <UpbitAutotradingSettingsWorkspace
      ubaId={ubaId}
      onUbaIdChange={onUbaIdChange}
    />
  );
}

export default function AdminUpbitAutotradingPage() {
  return (
    <AdminPageShell
      title="업비트 자동매매 설정"
      description="전체시장 · 자금/포지션 · 진입/청산 · AI · 안전 한도. PORTFOLIO 자동 Enable 및 REAL 주문 없음."
    >
      <Suspense fallback={<Spin />}>
        <UpbitAutotradingPageBody />
      </Suspense>
    </AdminPageShell>
  );
}
