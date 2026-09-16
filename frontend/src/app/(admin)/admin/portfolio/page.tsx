"use client";

import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { HoldingsOwnershipWorkspace } from "@/features/admin/portfolio/HoldingsOwnershipWorkspace";

export default function AdminPortfolioPage() {
  return (
    <AdminPageShell
      title="보유자산·손익"
      description="내 돈이 지금 어떻게 되어 있는지 보는 기준 화면입니다. LIVE/ARM·런타임 상태는 계좌·자동매매 화면에서 확인하세요."
    >
      <HoldingsOwnershipWorkspace />
    </AdminPageShell>
  );
}
